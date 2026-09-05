import {processFixture, summaryFixture} from "./review-contract-fixtures";
import {describe, expect, it} from "vitest";

import {
  canTransition,
  checkConclusionForResult,
  deadlineMinutes,
  isDeadlineReached,
  shouldRestartForRerequest,
  parseArtifactSummary,
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
  it.each([
    ["pass", 0, "success", "completed"], ["block", 1, "failure", "completed"],
    ["invalid", 2, "neutral", "failed"], ["infra_failed", 3, "neutral", "failed"],
  ])("maps process status %s and exit code %s", (status, exitCode, conclusion, terminalState) => {
    expect(checkConclusionForResult(Number(exitCode), JSON.stringify(processFixture({
      status, exit_code: exitCode,
      failure: ["infra_failed", "invalid"].includes(String(status)) ? {code: "review_failed", detail: "no valid lanes"} : null,
    })))).toMatchObject({terminalState, conclusion});
  });
  it.each([
    [0, "not json"],
    [1, '{"verdict":"BLOCK","run_id":"run-1"}'],
    [1, '{"schema_version":1,"status":"pass","exit_code":0,"run_id":"run-1"}'],
    [0, '{"schema_version":2,"status":"pass","exit_code":0,"run_id":"run-1"}'],
    [0, '{"schema_version":1,"status":"block","exit_code":0,"run_id":"run-1"}'],
  ])("rejects stdout envelopes, mismatches and invalid process contracts %#", (code, output) => {
    expect(checkConclusionForResult(Number(code), String(output))).toMatchObject({
      terminalState: "failed", conclusion: "neutral",
    });
  });
  it("preserves the machine-readable Python failure reason", () => {
    expect(checkConclusionForResult(3, JSON.stringify(processFixture({
      status: "infra_failed", exit_code: 3, failure: {code: "review_failed", detail: "all invalid"},
    }))).reason).toBe("review_failed: all invalid");
  });
});

describe("Python artifact summary", () => {
  it("uses the shared facts and markdown without recounting stages", () => {
    const summary = {schema_version: 1, lanes: {dispatched: 3, valid: 2, uncovered: 1},
      findings: {blocker: 1, warning: 2, suggestion: 0},
      verdicts: {CONFIRMED: 1, REJECTED: 0, UNCERTAIN: 0}, blockers: ["group-1"],
      markdown: "Shared Python summary with two valid lanes."};
    expect(parseArtifactSummary(JSON.stringify(summary))).toMatchObject({
      lanes: summary.lanes, markdown: summary.markdown,
    });
  });
  it("rejects zero-valid coverage", () => {
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture({
      lanes: {dispatched: 3, valid: 0, uncovered: 1}, markdown: ""})))).toThrow(/valid/i);
  });
  it("rejects malformed summary artifacts", () => {
    expect(() => parseArtifactSummary("{}")).toThrow(/artifact/i);
  });
});


it.each(["target", "runtime", "artifacts", "effective_policy", "failure"])(
  "rejects process contracts missing %s", (field) => {
    const process: Record<string, unknown> = processFixture();
    delete process[field];
    expect(checkConclusionForResult(0, JSON.stringify(process)).conclusion).toBe("neutral");
  },
);
it.each(["findings", "verdicts", "blockers"])("rejects summaries missing %s", (field) => {
  const summary: Record<string, unknown> = summaryFixture();
  delete summary[field];
  expect(() => parseArtifactSummary(JSON.stringify(summary))).toThrow(/fields/);
});
it("rejects incompatible failure and unknown process fields", () => {
  for (const overrides of [{unexpected: true}, {status: "infra_failed", exit_code: 3, failure: null},
    {failure: {code: "infra", detail: "error"}}]) {
    expect(checkConclusionForResult(null, JSON.stringify(processFixture(overrides))).conclusion).toBe("neutral");
  }
});
