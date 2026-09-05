import {processFixture, summaryFixture} from "./review-contract-fixtures";
import type {Process} from "@cloudflare/sandbox";
import {beforeEach, describe, expect, it, vi} from "vitest";

const mocks = vi.hoisted(() => ({
  sandboxFor: vi.fn(), configureOutbound: vi.fn(),
  getInstallationToken: vi.fn(async () => "installation-placeholder"),
  clearInstallationToken: vi.fn(), updateCheckRun: vi.fn(async (_token: string, _request: {summary: string}) => {}),
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
vi.mock("./github-app", () => ({...mocks, createCheckRun: vi.fn(async () => ({id: 42}))}));

import {RvwReviewJob} from "./review-job";
import {idempotencyKey, type ReviewJobMessage} from "./webhook";

const message: ReviewJobMessage = {
  jobId: idempotencyKey(17, 23, 42, "a".repeat(40)),
  idempotencyKey: idempotencyKey(17, 23, 42, "a".repeat(40)),
  installationId: 17, repoId: 23, owner: "acme", repo: "rockets", prNumber: 42,
  headSha: "a".repeat(40), baseSha: "b".repeat(40), event: "pull_request.opened",
  attempt: 1, deliveryId: "delivery-1", enqueuedAt: "2026-09-05T00:00:00.000Z",
};
function setup(state: string) {
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
  const env = {CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1", RVW_ARTIFACTS: {put}} as unknown as Env;
  return {job: new RvwReviewJob(ctx, env), events, put, sandbox, storage, files, record: () => record};
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
