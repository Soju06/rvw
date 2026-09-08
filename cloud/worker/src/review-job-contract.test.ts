import {processFixture, publishFactsFixture, summaryFixture, waveWallFixture} from "./review-contract-fixtures";
import {describe, expect, it} from "vitest";

import {
  canTransition,
  checkConclusionForResult,
  isDeadlineReached,
  shouldRestartForRerequest,
  parseArtifactSummary,
  parseProcessResult,
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
      lanes: {...summary.lanes, uncovered_regions: null}, markdown: summary.markdown,
    });
  });
  it("keeps lane-hunk receipts and distinct uncovered regions as separate facts", () => {
    const parsed = parseArtifactSummary(JSON.stringify(summaryFixture({
      lanes: {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: 13}})));
    expect(parsed.lanes).toEqual({dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: 13});
  });
  it.each([
    {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: 27},
    {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: -1},
    {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: 1.5},
    {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: "13"},
  ])("rejects inconsistent uncovered region counts %#", (lanes) => {
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture({lanes})))).toThrow();
  });
  it("rejects zero-valid coverage", () => {
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture({
      lanes: {dispatched: 3, valid: 0, uncovered: 1}, markdown: ""})))).toThrow(/valid/i);
  });
  it("rejects malformed summary artifacts", () => {
    expect(() => parseArtifactSummary("{}")).toThrow(/artifact/i);
  });
  it("passes through failed lanes and per-wave wall seconds from Python", () => {
    const failed = [{lane_id: "correctness", reason: "exit_nonzero:124"}, {lane_id: "hygiene", reason: "exit_nonzero:124"}];
    const walls = waveWallFixture({discovery_initial: 600.134, discovery_retry: 600.085, adjudication_initial: 600.144});
    const parsed = parseArtifactSummary(JSON.stringify(summaryFixture({
      lanes: {dispatched: 6, valid: 4, uncovered: 26}, failed_lanes: failed, wave_wall_seconds: walls})));
    expect(parsed.failed_lanes).toEqual(failed);
    expect(parsed.wave_wall_seconds).toEqual(walls);
  });
  it("passes through publication facts and the skip reason from Python", () => {
    const publish = publishFactsFixture({event: "REQUEST_CHANGES", policy_source: "repository", actor: "review-bot[bot]",
      dismissed_review_ids: [17, 18], resolved_thread_ids: ["PRRT_1"], reused_thread_ids: ["PRRT_2"],
      threads_skipped_lane_invalid: ["PRRT_3"], threads_skipped_reason: null});
    const parsed = parseArtifactSummary(JSON.stringify(summaryFixture({publish, publication_skipped: "duplicate_review_same_head"})));
    expect(parsed.publish).toEqual(publish);
    expect(parsed.publication_skipped).toBe("duplicate_review_same_head");
    expect(parseArtifactSummary(JSON.stringify(summaryFixture({publish, publication_skipped: null}))).publication_skipped).toBeNull();
  });
  it("defaults legacy summaries without publication facts", () => {
    expect(parseArtifactSummary(JSON.stringify(summaryFixture()))).toMatchObject({publish: null, publication_skipped: null});
  });
  it.each([
    {publish: publishFactsFixture({event: "DISMISS"})},
    {publish: publishFactsFixture({policy_source: "head"})},
    {publish: publishFactsFixture({dismissed_review_ids: ["17"]})},
    {publish: publishFactsFixture({resolved_thread_ids: [1]})},
    {publish: publishFactsFixture({resolved_thread_ids: [""]})},
    {publish: publishFactsFixture({extra: true})},
    {publish: {event: "COMMENT"}},
    {publish: "COMMENT"},
    {publication_skipped: ""},
    {publication_skipped: 3},
  ])("rejects malformed publication facts %#", (overrides) => {
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture(overrides)))).toThrow();
  });
  it("defaults legacy summaries without failure or wave facts", () => {
    const summary: Record<string, unknown> = summaryFixture();
    delete summary.failed_lanes;
    delete summary.wave_wall_seconds;
    expect(parseArtifactSummary(JSON.stringify(summary))).toMatchObject({failed_lanes: [], wave_wall_seconds: null});
  });
  it.each([
    {failed_lanes: [{lane_id: "", reason: "empty"}]},
    {failed_lanes: [{lane_id: "lane"}]},
    {failed_lanes: [{lane_id: "lane", reason: "empty", extra: 1}]},
    {failed_lanes: "correctness"},
    {wave_wall_seconds: waveWallFixture({discovery_initial: -1})},
    {wave_wall_seconds: {...waveWallFixture(), unknown_wave: 1}},
    {wave_wall_seconds: {discovery_initial: 1}},
    {wave_wall_seconds: waveWallFixture({adjudication_initial: "600" as unknown as number})},
  ])("rejects malformed failure or wave facts %#", (overrides) => {
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture(overrides)))).toThrow();
  });
});


it.each(["none", "github-review", "github-comment"])("accepts runtime.publish %s", (publish) => {
  const process = processFixture();
  (process.runtime as Record<string, unknown>).publish = publish;
  expect(checkConclusionForResult(0, JSON.stringify(process)).conclusion).toBe("success");
});
it("rejects an unknown runtime.publish value", () => {
  const process = processFixture();
  (process.runtime as Record<string, unknown>).publish = "github-approve";
  expect(checkConclusionForResult(0, JSON.stringify(process)).conclusion).toBe("neutral");
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

it("consumes the resolved presentation snapshot from process and summary", () => {
  const presentation = {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko", footer: null};
  expect(checkConclusionForResult(0, JSON.stringify(processFixture({presentation}))).conclusion).toBe("success");
  expect(parseArtifactSummary(JSON.stringify(summaryFixture({presentation})))).toMatchObject({presentation});
});
it.each([
  null,
  {display_name: "", short_name: "rvw", locale: "en", footer: null},
  {display_name: "rvw", short_name: "rvw", locale: "fr", footer: null},
  {display_name: "rvw", short_name: "rvw\nname", locale: "en", footer: null},
  {display_name: "rvw", short_name: "rvw", locale: "en", footer: null, extra: true},
])("rejects malformed presentation snapshots %#", (presentation) => {
  expect(checkConclusionForResult(0, JSON.stringify(processFixture({presentation}))).conclusion).toBe("neutral");
  expect(() => parseArtifactSummary(JSON.stringify(summaryFixture({presentation})))).toThrow();
});

it("defaults legacy process and summary contracts without presentation", () => {
  const process: Record<string, unknown> = processFixture();
  const summary: Record<string, unknown> = summaryFixture();
  delete process.presentation;
  delete summary.presentation;
  expect(checkConclusionForResult(0, JSON.stringify(process)).conclusion).toBe("success");
  expect(parseArtifactSummary(JSON.stringify(summary)).presentation).toEqual({
    display_name: "rvw", short_name: "rvw", locale: "en", footer: null,
  });
});

it("accepts strict language publication facts from Python", () => {
  const presentation = {display_name: "VOOY", short_name: "Review", locale: "ko", footer: null};
  const process = processFixture({presentation, status: "infra_failed", exit_code: 3,
    failure: {code: "publication_language_mismatch", detail: "language"},
    publication_failure: "publication_language_mismatch", language_fallback_used: false});
  expect(checkConclusionForResult(3, JSON.stringify(process)).reasonCode).toBe("publication_language_mismatch");
  const summary = summaryFixture({presentation, publication_failure: null, language_fallback_used: true});
  expect(parseArtifactSummary(JSON.stringify(summary))).toMatchObject({language_fallback_used: true});
  expect(() => parseArtifactSummary(JSON.stringify({...summary, language_fallback_used: "true"}))).toThrow();
  expect(() => parseArtifactSummary(JSON.stringify({...summary, publication_failure: ""}))).toThrow();
});

it("accepts and preserves publication language outcome facts", () => {
  const publication = {publication_failure: "publication_language_mismatch", language_fallback_used: true};
  expect(checkConclusionForResult(0, JSON.stringify(processFixture(publication)))).toMatchObject({conclusion: "success", ...publication});
  expect(parseArtifactSummary(JSON.stringify(summaryFixture(publication)))).toMatchObject(publication);
});
it.each([{publication_failure: 1}, {language_fallback_used: "true"}, {language_fallback_used: null}])(
  "rejects invalid publication language contract %#", (publication) => {
    expect(checkConclusionForResult(0, JSON.stringify(processFixture(publication))).conclusion).toBe("neutral");
    expect(() => parseArtifactSummary(JSON.stringify(summaryFixture(publication)))).toThrow();
  },
);

describe("process runtime watchdog settings", () => {
  it("accepts the recorded no-output watchdog and reasoning summary settings", () => {
    const runtime = processFixture().runtime as Record<string, unknown>;
    expect(runtime).toMatchObject({no_output_seconds: 660, reasoning_summary: "detailed"});
    expect(checkConclusionForResult(0, JSON.stringify(processFixture())).conclusion).toBe("success");
  });
  it("parses legacy runtime settings without the watchdog and summary keys", () => {
    const process = processFixture();
    const runtime: Record<string, unknown> = {...(process.runtime as Record<string, unknown>)};
    delete runtime.no_output_seconds;
    delete runtime.reasoning_summary;
    expect(checkConclusionForResult(0, JSON.stringify({...process, runtime})).conclusion).toBe("success");
  });
  it.each([
    {no_output_seconds: 0},
    {no_output_seconds: -1},
    {no_output_seconds: "660"},
    {reasoning_summary: ""},
    {reasoning_summary: 1},
  ])("rejects invalid watchdog or summary settings %#", (overrides) => {
    const process = processFixture();
    const runtime = {...(process.runtime as Record<string, unknown>), ...overrides};
    expect(() => parseProcessResult(JSON.stringify({...process, runtime}))).toThrow("process runtime settings are invalid");
  });
});
