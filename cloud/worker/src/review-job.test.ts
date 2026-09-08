import {processFixture, publishFactsFixture, summaryFixture, waveWallFixture} from "./review-contract-fixtures";
import type {PresentationConfig} from "./presentation";
import type {UpdateCheckRunInput} from "./github-app";
import type {Process} from "@cloudflare/sandbox";
import {beforeEach, describe, expect, it, vi} from "vitest";

const mocks = vi.hoisted(() => ({
  sandboxFor: vi.fn(), configureOutbound: vi.fn(),
  getInstallationToken: vi.fn(async () => "installation-placeholder"),
  getPresentationConfig: vi.fn(async (): Promise<{presentation: PresentationConfig; failure?: string}> => ({presentation: {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko" as const, footer: null}, failure: undefined as string | undefined})),
  createCheckRun: vi.fn(async () => ({id: 42, appSlug: "review-app"})),
  getCheckRunAppSlug: vi.fn(async () => "review-app"),
  clearInstallationToken: vi.fn(), updateCheckRun: vi.fn(async (_token: string, _request: UpdateCheckRunInput) => {}),
}));
vi.mock("cloudflare:workers", () => ({DurableObject: class {
  constructor(protected ctx: unknown, protected env: unknown) {}
}}));
vi.mock("./sandbox", () => ({
  sandboxFor: mocks.sandboxFor, configureOutbound: mocks.configureOutbound,
  optionalFile: async (sandbox: {readFile(path: string): Promise<{content: string}>}, path: string) => {
    try { return (await sandbox.readFile(path)).content; } catch { return null; }
  },
  readTextFile: async (sandbox: {readFile(path: string): Promise<{content: string}>}, path: string) =>
    (await sandbox.readFile(path)).content,
}));
vi.mock("./github-app", async (importOriginal) => ({...await importOriginal<typeof import("./github-app")>(), ...mocks}));

import {RvwReviewJob, reviewScript} from "./review-job";
import {idempotencyKey, type ReviewJobMessage} from "./webhook";

const message: ReviewJobMessage = {
  jobId: idempotencyKey(17, 23, 42, "a".repeat(40)),
  idempotencyKey: idempotencyKey(17, 23, 42, "a".repeat(40)),
  installationId: 17, repoId: 23, owner: "acme", repo: "rockets", prNumber: 42,
  headSha: "a".repeat(40), baseSha: "b".repeat(40), event: "pull_request.opened",
  attempt: 1, deliveryId: "delivery-1", enqueuedAt: "2026-09-05T00:00:00.000Z",
};
function setup(state: string, envOverrides: Record<string, string> = {}) {
  let record: Record<string, unknown> = {
    schemaVersion: 1, jobId: message.jobId, message, state,
    createdAt: message.enqueuedAt, updatedAt: message.enqueuedAt,
    deadlineAt: "2020-01-01T00:00:00.000Z", sandboxId: "sandbox-1", processId: "process-1",
    checkRunId: 42, artifacts: [],
  };
  const events: string[] = [];
  const files = new Map<string, string>([
    ["/workspace/result/run.log", "runtime diagnostic\n"],
    ["/workspace/result/environment.txt", "RVW_CODEX_SANDBOX=danger-full-access\n"],
    ["/workspace/result/process.json", JSON.stringify({schema_version: 1, artifacts: [
      {path: "run.log", size_bytes: 19}, {path: "process.json", size_bytes: 1},
      {path: "environment.txt", size_bytes: 42},
    ]})],
  ]);
  const sandbox = {
    getProcess: vi.fn(async (): Promise<Process | null> => null),
    getProcessLogs: vi.fn(async () => ({stdout: "runtime diagnostic\n", stderr: ""})),
    killProcess: vi.fn(async () => { events.push("kill"); }),
    removeOutboundByHost: vi.fn(), destroy: vi.fn(async () => { events.push("destroy"); }),
    readFile: vi.fn(async (path: string) => {
      const content = files.get(path);
      if (content === undefined) throw new Error("not found");
      return {content};
    }),
    writeFile: vi.fn(async (path: string, content: string) => { files.set(path, content); }),
    exec: vi.fn(async (_command: string) => { events.push("exec"); return {success: true, exitCode: 0}; }),
    startProcess: vi.fn(async () => { throw new Error("process failed to start"); }),
  };
  const storage = {
    get: vi.fn(async () => record),
    put: vi.fn(async (_key: string, value: Record<string, unknown>) => { record = value; }),
    setAlarm: vi.fn(),
  };
  mocks.sandboxFor.mockReturnValue(sandbox);
  const put = vi.fn(async (key: string, value: string) => {
    events.push(`put:${key.split("/").at(-1)}`);
    return {key, size: value.length, etag: "etag", uploaded: new Date()};
  });
  const ctx = {storage} as unknown as DurableObjectState;
  const env = {CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1", RVW_REVIEW_DEADLINE_SECONDS: "900",
    RVW_JOB_DEADLINE_MINUTES: "120", RVW_ARTIFACTS: {put}, ...envOverrides} as unknown as Env;
  return {job: new RvwReviewJob(ctx, env), events, put, sandbox, storage, files, record: () => record};
}
function startOptions(call: unknown[]): {env: Record<string, string>} {
  return (call as [string, {env: Record<string, string>}])[1];
}
beforeEach(() => { vi.clearAllMocks(); });
describe("terminal diagnostic persistence", () => {
  it.each(["timeout", "start failure", "supersession"])(
    "persists all diagnostics before Sandbox destruction after %s", async (path) => {
      const test = setup(path === "start failure" ? "provisioning" : "running");
      if (path === "timeout") await test.job.alarm();
      else if (path === "start failure") await test.job.failStart(message, "launch failed");
      else await test.job.supersede(message.jobId, "new head");
      for (const name of ["run.log", "process.json", "environment.txt"]) {
        expect(test.events).toContain(`put:${name}`);
        expect(test.events.indexOf(`put:${name}`)).toBeLessThan(test.events.indexOf("destroy"));
      }
      expect(test.record().conclusion).toBe("neutral");
    },
  );
});


it("initializes diagnostics before an actual SDK start failure and finalizes through Python", async () => {
  const test = setup("provisioning");
  delete test.record().processId;
  await expect(test.job.start(message)).rejects.toThrow("process failed to start");
  await test.job.failStart(message, "process failed to start");
  expect(test.sandbox.exec.mock.calls[0][0]).toContain("python -m rvw.store initialize");
  expect(test.sandbox.exec.mock.calls.some(([command]) =>
    command.includes("python -m rvw.store finalize") && command.includes("--failure-code 'start_failed'"),
  )).toBe(true);
  expect(test.events.indexOf("put:process.json")).toBeLessThan(test.events.indexOf("destroy"));
  expect(test.sandbox.writeFile.mock.calls.every(([path]) => !path.endsWith("process.json"))).toBe(true);
});

it("writes the review script with the explicit configured deadline and a matching job cap", async () => {
  const test = setup("provisioning");
  delete test.record().processId;
  await expect(test.job.start(message)).rejects.toThrow("process failed to start");
  const script = test.sandbox.writeFile.mock.calls.find(([path]) => path === "/workspace/run-review.sh")?.[1];
  expect(script).toContain("--deadline 900 --policy auto --publish github-review --json");
  expect(script).toBe(reviewScript(message, 900));
  expect(reviewScript(message, 1200)).toContain("--deadline 1200 ");
});

it("fails closed before provisioning when the job cap cannot cover the review budget", async () => {
  const test = setup("provisioning", {RVW_JOB_DEADLINE_MINUTES: "84"});
  await expect(test.job.start(message)).rejects.toMatchObject({code: "config_incoherent",
    reason: "job_deadline_below_review_budget", minimumJobDeadlineMinutes: 85});
  expect(mocks.createCheckRun).not.toHaveBeenCalled();
  expect(mocks.sandboxFor).not.toHaveBeenCalled();
});

it("passes the App bot login into the review process from the created check run", async () => {
  const test = setup("provisioning");
  delete test.record().checkRunId;
  delete test.record().processId;
  test.sandbox.startProcess.mockImplementationOnce((async () => ({id: "process-2", command: "/workspace/run-review.sh",
    startTime: new Date("2026-09-07T10:13:27.000Z")})) as never);
  await test.job.start(message);
  expect(test.record().appSlug).toBe("review-app");
  const options = startOptions(test.sandbox.startProcess.mock.calls[0]);
  expect(options.env.RVW_GITHUB_LOGIN).toBe("review-app[bot]");
  expect(mocks.getCheckRunAppSlug).not.toHaveBeenCalled();
});

it("reads the App slug back when re-entering with an existing check run", async () => {
  const test = setup("provisioning");
  delete test.record().processId;
  test.sandbox.startProcess.mockImplementationOnce((async () => ({id: "process-2", command: "/workspace/run-review.sh",
    startTime: new Date("2026-09-07T10:13:27.000Z")})) as never);
  await test.job.start(message);
  expect(mocks.createCheckRun).not.toHaveBeenCalled();
  expect(mocks.getCheckRunAppSlug).toHaveBeenCalledWith("installation-placeholder", {owner: "acme", repo: "rockets", checkRunId: 42});
  const options = startOptions(test.sandbox.startProcess.mock.calls[0]);
  expect(options.env.RVW_GITHUB_LOGIN).toBe("review-app[bot]");
});

it("starts without a login when the slug cannot be read, and still reviews", async () => {
  const test = setup("provisioning");
  delete test.record().processId;
  mocks.getCheckRunAppSlug.mockRejectedValueOnce(new Error("HTTP 500"));
  test.sandbox.startProcess.mockImplementationOnce((async () => ({id: "process-2", command: "/workspace/run-review.sh",
    startTime: new Date("2026-09-07T10:13:27.000Z")})) as never);
  await test.job.start(message);
  const options = startOptions(test.sandbox.startProcess.mock.calls[0]);
  expect(options.env).not.toHaveProperty("RVW_GITHUB_LOGIN");
  expect(test.record().state).toBe("running");
});

it("uses the configured job cap for the deadline recorded at start", async () => {
  const test = setup("provisioning");
  test.sandbox.startProcess.mockImplementationOnce((async () => ({id: "process-2", command: "/workspace/run-review.sh",
    startTime: new Date("2026-09-07T10:13:27.000Z")})) as never);
  const before = Date.now();
  await test.job.start(message);
  const deadlineAt = Date.parse(test.record().deadlineAt as string);
  expect(deadlineAt - before).toBeGreaterThanOrEqual(120 * 60_000 - 5_000);
  expect(deadlineAt - before).toBeLessThanOrEqual(120 * 60_000 + 5_000);
});

it("continues all artifact attempts after an R2 failure", async () => {
  const test = setup("running");
  test.put.mockRejectedValueOnce(new Error("R2 unavailable"));
  await test.job.supersede(message.jobId, "new head");
  expect(test.put).toHaveBeenCalledTimes(3);
  expect(test.events).toContain("put:process.json");
  expect(test.events).toContain("put:environment.txt");
  expect(test.events.at(-1)).toBe("destroy");
  expect(test.record()).toMatchObject({state: "superseded", conclusion: "neutral"});
});

it("records a forced termination request without inventing an SDK signal", async () => {
  const test = setup("running");
  await test.job.alarm();
  const finalizer = test.sandbox.exec.mock.calls.find(([command]) => command.includes(" finalize "))?.[0];
  expect(finalizer).toContain("--failure-code 'timed_out'");
  expect(finalizer).toContain('"signal":null');
  expect(test.events.indexOf("kill")).toBeLessThan(test.events.indexOf("exec"));
});

it.each([
  ["pass", 0, 1, "success"], ["block", 1, 1, "failure"],
  ["invalid", 2, 0, "neutral"], ["infra_failed", 3, 0, "neutral"],
  ["pass", 0, 0, "neutral"],
])("publishes process status %s with %s exit and %s valid lanes as %s", async (status, code, valid, conclusion) => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  const process = {id: "process-1", command: "/workspace/run-review.sh", status: "completed",
    startTime: new Date("2026-09-05T00:00:00Z"), exitCode: Number(code)} as Process;
  test.sandbox.getProcess.mockResolvedValue(process);
  const previous = JSON.parse(test.files.get("/workspace/result/process.json")!);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({...previous,
    status, exit_code: code, failure: ["infra_failed", "invalid"].includes(String(status)) ? {code: "review_failed", detail: "all invalid"} : null})));
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture({
    lanes: {dispatched: 1, valid, uncovered: 0}})));
  refreshManifest(test.files);
  await test.job.alarm();
  expect(mocks.updateCheckRun).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({conclusion}));
  if (Number(valid) > 0) {
    expect(mocks.updateCheckRun.mock.calls[0][1].summary).toContain("Canonical Python counts.");
  }
  expect(test.sandbox.exec.mock.calls.some(([command]) => command.includes("--failure-code 'start_failed'"))).toBe(false);
  expect(test.record().conclusion).toBe(conclusion);
});

it("puts failed lanes, per-wave walls, receipts, and distinct regions into the check text", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "/workspace/run-review.sh", status: "completed",
    startTime: new Date("2026-09-07T10:13:27Z"), exitCode: 0} as Process);
  const previous = JSON.parse(test.files.get("/workspace/result/process.json")!);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({...previous, status: "pass", exit_code: 0, failure: null})));
  // Shape of bori#1744 after the dead-lane skip: 6 lanes, 4 valid, 13 regions uncovered by 2 dead lanes.
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture({
    presentation: {display_name: "rvw", short_name: "rvw", locale: "ko", footer: null},
    lanes: {dispatched: 6, valid: 4, uncovered: 26, uncovered_regions: 13},
    failed_lanes: [{lane_id: "correctness", reason: "exit_nonzero:124"}, {lane_id: "hygiene", reason: "exit_nonzero:124"}],
    wave_wall_seconds: waveWallFixture({discovery_initial: 600.134, discovery_retry: 600.085, adjudication_initial: 600.144}),
    markdown: "검토를 마쳤습니다. 수정이 필요한 문제 0건, 확인이 필요한 항목 0건. 검토되지 않은 변경 구간이 13곳 있습니다. 검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene.",
  })));
  refreshManifest(test.files);
  await test.job.alarm();
  const update = mocks.updateCheckRun.mock.calls[0][1];
  expect(update.conclusion).toBe("success");
  expect(update.summary).toContain("검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene.");
  const facts = JSON.parse(update.text!.split("```json\n")[1].split("\n```")[0]);
  expect(facts.lanes).toEqual({dispatched: 6, valid: 4, lane_hunk_receipts: 26, uncovered_regions: 13});
  expect(facts.failed_lanes).toEqual([{lane_id: "correctness", reason: "exit_nonzero:124"}, {lane_id: "hygiene", reason: "exit_nonzero:124"}]);
  expect(facts.wave_wall_seconds).toMatchObject({discovery_initial: 600.134, discovery_retry: 600.085,
    discovery_redispatch: null, adjudication_initial: 600.144, adjudication_expanded: null});
  expect(facts).not.toHaveProperty("uncovered");
});

it("carries the publication facts and skip reason verbatim into the check text", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "/workspace/run-review.sh", status: "completed",
    startTime: new Date("2026-09-07T10:13:27Z"), exitCode: 1} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({status: "block", exit_code: 1, failure: null,
    runtime: {...(processFixture().runtime as Record<string, unknown>), publish: "github-review"}})));
  const publish = publishFactsFixture({event: "REQUEST_CHANGES", policy_source: "repository", actor: "review-app[bot]",
    resolved_thread_ids: ["PRRT_1"], reused_thread_ids: ["PRRT_2"], threads_skipped_lane_invalid: ["PRRT_3"]});
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture({publish, publication_skipped: null,
    markdown: "Review complete. Changes required: 1. Needs attention: 0."})));
  refreshManifest(test.files);
  await test.job.alarm();
  const update = mocks.updateCheckRun.mock.calls[0][1];
  expect(update.conclusion).toBe("failure");
  expect(update.summary).toBe("Review complete. Changes required: 1. Needs attention: 0.");
  const facts = JSON.parse(update.text!.split("```json\n")[1].split("\n```")[0]);
  expect(facts.publish).toEqual(publish);
  expect(facts.publication_skipped).toBeNull();
});

it("shows the publish policy reason when Python exits 2 on publish_policy_invalid", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed", startTime: new Date(), exitCode: 2} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({status: "invalid", exit_code: 2,
    failure: {code: "publish_policy_invalid", detail: "approve_not_opted_in"}})));
  refreshManifest(test.files);
  await test.job.alarm();
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output.conclusion).toBe("neutral");
  expect(output.summary).toBe("The repository publish policy is invalid.");
  expect(output.text).toContain("publish_policy_invalid");
});

it("persists diagnostics when a Sandbox process disappears", async () => {
  const test = setup("running");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  await test.job.alarm();
  expect(test.sandbox.exec.mock.calls.some(([command]) => command.includes("--failure-code 'process_disappeared'"))).toBe(true);
  for (const name of ["run.log", "process.json", "environment.txt"]) {
    expect(test.events.indexOf(`put:${name}`)).toBeLessThan(test.events.indexOf("destroy"));
  }
  expect(test.record().conclusion).toBe("neutral");
});


function refreshManifest(files: Map<string, string>): void {
  const path = "/workspace/result/process.json";
  const process = JSON.parse(files.get(path)!);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    process.artifacts = [...files].map(([name, content]) => ({
      path: name.replace("/workspace/result/", ""), size_bytes: new TextEncoder().encode(content).length,
    }));
    const content = JSON.stringify(process);
    if (content === files.get(path)) return;
    files.set(path, content);
  }
}

it.each(["missing", "malformed"])("persists the other diagnostics when process.json is %s", async (condition) => {
  const test = setup("running");
  if (condition === "missing") test.files.delete("/workspace/result/process.json");
  else test.files.set("/workspace/result/process.json", "{broken");
  await test.job.supersede(message.jobId, "new head");
  expect(test.events).toContain("put:run.log");
  expect(test.events).toContain("put:environment.txt");
  expect(test.events.indexOf("put:environment.txt")).toBeLessThan(test.events.indexOf("destroy"));
  expect(test.record().conclusion).toBe("neutral");
});

it("does not finalize a process still active after the bounded termination check", async () => {
  const test = setup("running");
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "running",
    startTime: new Date()} as Process);
  await test.job.supersede(message.jobId, "new head");
  expect(test.sandbox.getProcess).toHaveBeenCalledTimes(6);
  expect(test.sandbox.exec).not.toHaveBeenCalled();
  expect(test.events).toContain("put:run.log");
  expect(test.events.at(-1)).toBe("destroy");
});

it("reports a manifest size mismatch and keeps the Check neutral", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed",
    startTime: new Date(), exitCode: 0} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({
    artifacts: [{path: "run.log", size_bytes: 999}],
  })));
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture()));
  await test.job.alarm();
  expect(test.record()).toMatchObject({conclusion: "neutral", artifactContractInvalid: true});
  expect(test.record().reason).toContain("manifest was invalid or inconsistent");
});

it("resolves bootstrap config before creating a check and allocating a sandbox", async () => {
  const test = setup("provisioning");
  delete test.record().checkRunId;
  delete test.record().sandboxId;
  delete test.record().processId;
  await expect(test.job.start(message)).rejects.toThrow("process failed to start");
  expect(mocks.getPresentationConfig).toHaveBeenCalledWith("installation-placeholder", {
    owner: message.owner, repo: message.repo, baseSha: message.baseSha,
  });
  expect(mocks.getPresentationConfig.mock.invocationCallOrder[0]).toBeLessThan(mocks.createCheckRun.mock.invocationCallOrder[0]);
  expect(mocks.createCheckRun.mock.invocationCallOrder[0]).toBeLessThan(mocks.sandboxFor.mock.invocationCallOrder[0]);
  expect(mocks.createCheckRun).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({presentation: expect.objectContaining({short_name: "VOOY Review"})}));
});
it.each(["timeout", "superseded", "queue"])("uses localized human-only summary for %s", async (path) => {
  const test = setup(path === "queue" ? "provisioning" : "running");
  test.record().presentation = {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko", footer: null};
  if (path === "timeout") await test.job.alarm();
  else if (path === "superseded") await test.job.supersede(message.jobId, "superseded by private-job");
  else await test.job.failStart(message, "Queue retries exhausted: stderr private-job");
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output.name).toBe("VOOY Review");
  expect(output.title).toBe("VOOY Review System · 검토 미완료");
  expect(output.summary).toMatch(/[가-힣]/);
  expect(output.summary).not.toMatch(/private-job|stderr|Artifacts|\d/);
  expect(output.text).toContain(message.jobId);
});
it.each([false, true])("renames the final check from Python and discloses bootstrap invalidity %s", async (bootstrapInvalid) => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.record().presentation = {display_name: "rvw", short_name: "rvw", locale: "en", footer: null};
  if (bootstrapInvalid) test.record().presentationConfigFailure = "presentation_config_invalid";
  const presentation = {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko", footer: null};
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed", startTime: new Date(), exitCode: 0} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({presentation})));
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture({presentation, markdown: "검토를 마쳤습니다. 수정이 필요한 문제 1건, 확인이 필요한 항목 2건."})));
  refreshManifest(test.files);
  await test.job.alarm();
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output.name).toBe("VOOY Review");
  expect(output.title).toBe("VOOY Review System · 검토 완료");
  expect(output.summary).toBe("검토를 마쳤습니다. 수정이 필요한 문제 1건, 확인이 필요한 항목 2건." +
    (bootstrapInvalid ? "\n\n저장소의 표시 설정이 올바르지 않습니다." : ""));
  expect(output.text).toContain('"valid": 1');
  expect(output.text).toContain(message.jobId);
});
it("reports invalid bootstrap configuration in the final neutral check", async () => {
  const test = setup("running");
  test.record().presentationConfigFailure = "presentation_config_invalid";
  await test.job.alarm();
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output.summary).toBe("The repository presentation configuration is invalid.");
  expect(output.text).toContain("presentation_config_invalid");
});
it("keeps Python branding when a missing summary makes the check neutral", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  const presentation = {display_name: "Resolved name", short_name: "Resolved", locale: "en", footer: null};
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed", startTime: new Date(), exitCode: 0} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({presentation})));
  refreshManifest(test.files);
  await test.job.alarm();
  expect(mocks.updateCheckRun.mock.calls[0][1]).toMatchObject({name: "Resolved", conclusion: "neutral"});
});
it("persists a malformed bootstrap diagnostic before creating the default check", async () => {
  const test = setup("provisioning");
  delete test.record().checkRunId;
  mocks.getPresentationConfig.mockResolvedValueOnce({presentation: {display_name: "rvw", short_name: "rvw", locale: "en", footer: null}, failure: "presentation_config_invalid"});
  await expect(test.job.start(message)).rejects.toThrow("process failed to start");
  expect(test.record().presentationConfigFailure).toBe("presentation_config_invalid");
  expect(test.storage.put.mock.invocationCallOrder[0]).toBeLessThan(mocks.createCheckRun.mock.invocationCallOrder[0]);
});
it("keeps the localized outcome counts on language mismatch and records fallback facts in text", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  const presentation = {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko", footer: null};
  const publication = {publication_failure: "publication_language_mismatch", language_fallback_used: false};
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed", startTime: new Date(), exitCode: 3} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({presentation, ...publication, status: "infra_failed", exit_code: 3,
    failure: {code: "publication_language_mismatch", detail: "Untranslated prose must never reach this summary"}})));
  const markdown = "검토를 마쳤습니다. 수정이 필요한 문제 1건, 확인이 필요한 항목 2건.";
  test.files.set("/workspace/result/summary.json", JSON.stringify(summaryFixture({presentation, ...publication, markdown})));
  refreshManifest(test.files);
  await test.job.alarm();
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output).toMatchObject({name: "VOOY Review", conclusion: "neutral", summary: markdown});
  expect(output.text).toContain('"publication_failure": "publication_language_mismatch"');
  expect(output.text).toContain('"language_fallback_used": false');
  expect(output.summary).not.toContain("Untranslated prose");
});
it("retains process language-fallback facts when summary is missing", async () => {
  const test = setup("publishing");
  test.record().deadlineAt = "2100-01-01T00:00:00.000Z";
  test.sandbox.getProcess.mockResolvedValue({id: "process-1", command: "rvw run", status: "completed", startTime: new Date(), exitCode: 0} as Process);
  test.files.set("/workspace/result/process.json", JSON.stringify(processFixture({publication_failure: "publication_language_mismatch", language_fallback_used: true})));
  refreshManifest(test.files);
  await test.job.alarm();
  const output = mocks.updateCheckRun.mock.calls[0][1];
  expect(output.conclusion).toBe("neutral");
  expect(output.text).toContain('"publication_failure": "publication_language_mismatch"');
  expect(output.text).toContain('"language_fallback_used": true');
});
