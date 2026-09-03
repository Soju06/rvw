import {describe, expect, it} from "vitest";

import {
  canTransition,
  checkConclusionForResult,
  deadlineMinutes,
  isDeadlineReached,
  shouldRestartForRerequest,
  summarizeArtifacts,
  type JobState,
} from "./review-job-contract";

describe("durable review state machine", () => {
  const allowed: Array<[JobState, JobState]> = [
    ["queued", "provisioning"],
    ["queued", "superseded"],
    ["provisioning", "running"],
    ["provisioning", "failed"],
    ["provisioning", "superseded"],
    ["running", "publishing"],
    ["running", "failed"],
    ["running", "timed_out"],
    ["running", "superseded"],
    ["publishing", "completed"],
    ["publishing", "failed"],
    ["publishing", "timed_out"],
    ["publishing", "superseded"],
  ];

  it.each(allowed)("allows %s -> %s", (from, to) => {
    expect(canTransition(from, to)).toBe(true);
  });

  it.each<JobState>(["completed", "failed", "timed_out", "superseded"])(
    "makes %s terminal",
    (state) => {
      for (const candidate of [
        "queued",
        "provisioning",
        "running",
        "publishing",
        "completed",
        "failed",
        "timed_out",
        "superseded",
      ] as JobState[]) {
        expect(canTransition(state, candidate)).toBe(false);
      }
    },
  );

  it("rejects skipped and reverse transitions", () => {
    expect(canTransition("queued", "running")).toBe(false);
    expect(canTransition("running", "provisioning")).toBe(false);
    expect(canTransition("publishing", "running")).toBe(false);
  });

  it("allows only a new check_run rerequest delivery to restart a terminal key", () => {
    expect(
      shouldRestartForRerequest("completed", "delivery-old", "check_run.rerequested", "delivery-new"),
    ).toBe(true);
    expect(
      shouldRestartForRerequest("completed", "delivery-old", "check_run.rerequested", "delivery-old"),
    ).toBe(false);
    expect(
      shouldRestartForRerequest("running", "delivery-old", "check_run.rerequested", "delivery-new"),
    ).toBe(false);
    expect(
      shouldRestartForRerequest("completed", "delivery-old", "pull_request.opened", "delivery-new"),
    ).toBe(false);
  });
});

describe("deadline semantics", () => {
  it.each([[undefined], [""], ["nope"], ["0"], ["-3"]])(
    "defaults invalid %s to 90 minutes",
    (value) => expect(deadlineMinutes(value)).toBe(90),
  );

  it("accepts a positive configured deadline", () => {
    expect(deadlineMinutes("120")).toBe(120);
  });

  it("does not time out before the exact hard deadline", () => {
    expect(isDeadlineReached(1_000, 1_001)).toBe(false);
    expect(isDeadlineReached(1_001, 1_001)).toBe(true);
  });
});

describe("check-run conclusion mapping", () => {
  it("maps a parseable PASS exit to success", () => {
    expect(checkConclusionForResult(0, '{"verdict":"PASS","run_id":"run-1"}')).toEqual({
      terminalState: "completed",
      conclusion: "success",
      reason: "rvw auto passed",
    });
  });

  it("maps a parseable BLOCK exit to failure", () => {
    expect(checkConclusionForResult(1, '{"verdict":"BLOCK","run_id":"run-1"}')).toEqual({
      terminalState: "completed",
      conclusion: "failure",
      reason: "rvw auto found a blocking result",
    });
  });

  it.each([
    [0, "not json"],
    [1, '{"verdict":"PASS"}'],
    [2, '{"verdict":"PASS"}'],
    [null, '{"verdict":"BLOCK"}'],
  ])("maps infrastructure or unparseable result %# to neutral", (exitCode, output) => {
    expect(checkConclusionForResult(exitCode, output)).toMatchObject({
      terminalState: "failed",
      conclusion: "neutral",
    });
  });
});

describe("artifact summary", () => {
  it("reports lane coverage, uncovered work, and finding verdicts", () => {
    const discover = JSON.stringify({
      findings: [{severity: "blocker"}, {severity: "warning"}, {severity: "warning"}],
      coverage: [
        {dispatched: 3, valid: 2, findings: 2, uncovered: ["src/a.py:1"]},
        {dispatched: 2, valid: 2, findings: 1, uncovered: ["src/b.py:2", "src/c.py:3"]},
      ],
    });
    const outcome = JSON.stringify({
      verdicts: {one: "CONFIRMED", two: "REJECTED", three: "UNCERTAIN"},
      unresolved: ["three"],
    });
    expect(summarizeArtifacts(discover, outcome)).toEqual({
      lanesDispatched: 5,
      lanesValid: 4,
      uncovered: 3,
      findings: 3,
      findingsBySeverity: {blocker: 1, warning: 2},
      verdicts: {CONFIRMED: 1, REJECTED: 1, UNCERTAIN: 1},
    });
  });

  it("rejects malformed required result JSON", () => {
    expect(() => summarizeArtifacts("{}", "{}")).toThrow(/artifact/i);
  });
});
