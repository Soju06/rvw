import {beforeEach, describe, expect, it, vi} from "vitest";

const mocks = vi.hoisted(() => ({sandboxFor: vi.fn(), configureOutbound: vi.fn(async () => {})}));
vi.mock("./sandbox", () => ({
  sandboxFor: mocks.sandboxFor, configureOutbound: mocks.configureOutbound,
  optionalFile: async () => null, processPayload: () => null,
}));

import {requiredConfig} from "./config";
import {handleRoute, start} from "./routes";

const REPO = "https://github.com/acme/rockets";
const TARGET = "0123456789abcdef0123456789abcdef01234567";
const START_URL = `https://worker.example/start?repo=${REPO}&target=${TARGET}`;
const BASE_ENV = {CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
  RVW_REVIEW_DEADLINE_SECONDS: "900", RVW_JOB_DEADLINE_MINUTES: "120"};

function fakeSandbox() {
  const files = new Map<string, string>();
  return {
    files,
    writeFile: vi.fn(async (path: string, content: string) => { files.set(path, content); }),
    exec: vi.fn(async () => ({success: true, exitCode: 0})),
    startProcess: vi.fn(async () => ({id: "process-1", command: "/workspace/run-review.sh", startTime: new Date()})),
  };
}

function setup(envOverrides: Record<string, string> = {}) {
  const sandbox = fakeSandbox();
  mocks.sandboxFor.mockReturnValue(sandbox);
  const env = {RVW_ENV: "spike", ...BASE_ENV, ...envOverrides} as unknown as Env;
  const config = requiredConfig(env as unknown as Record<string, string>);
  return {sandbox, env, config};
}

function post(url: string, body?: string, contentType = "application/json"): Request {
  return new Request(url, {method: "POST", ...(body === undefined ? {} : {body, headers: {"content-type": contentType}})});
}

function runLine(sandbox: ReturnType<typeof fakeSandbox>): string {
  const script = sandbox.files.get("/workspace/run-review.sh");
  expect(script).toBeDefined();
  const line = script!.split("\n").find((candidate) => candidate.includes("python -m rvw.container_entrypoint run "));
  expect(line).toBeDefined();
  return line!;
}

beforeEach(() => { vi.clearAllMocks(); });

describe("POST /start Codex runtime overrides", () => {
  it("keeps working without a body and leaves the CLI default in place", async () => {
    const {sandbox, env, config} = setup();
    const response = await handleRoute(post(START_URL), env, config);
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toEqual({sandboxId: expect.stringMatching(/^rvw-spike-/), processId: "process-1",
      repo: REPO, target: TARGET, model: null, reasoning_effort: null});
    const line = runLine(sandbox);
    expect(line.endsWith(`--target '${TARGET}' --repo-dir "$TARGET" --out "$RESULT" --deadline 900 --policy auto --publish none --json`)).toBe(true);
    expect(line).not.toContain("--model");
    expect(line).not.toContain("--reasoning-effort");
    expect(sandbox.startProcess).toHaveBeenCalledWith("/workspace/run-review.sh", {env: {
      CODEX_API_KEY: "placeholder-not-a-secret", CODEX_BASE_URL: "https://proxy.example/backend-api/codex"}});
    expect(mocks.configureOutbound).toHaveBeenCalledWith(sandbox, "proxy.example");
  });

  it.each(["", "   \n"])("treats a blank body %# like no body", async (body) => {
    const {sandbox, env, config} = setup();
    const response = await start(post(START_URL, body), env, config, new URL(START_URL));
    expect(response.status).toBe(202);
    expect(runLine(sandbox)).not.toContain("--model");
  });

  it("writes the body overrides into the script shell-quoted after --json and echoes them", async () => {
    const {sandbox, env, config} = setup();
    const response = await handleRoute(post(START_URL, JSON.stringify({model: "gpt-6-astra", reasoning_effort: "high"})), env, config);
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toMatchObject({repo: REPO, target: TARGET, model: "gpt-6-astra", reasoning_effort: "high"});
    const line = runLine(sandbox);
    expect(line.endsWith("--deadline 900 --policy auto --publish none --json --model 'gpt-6-astra' --reasoning-effort 'high'")).toBe(true);
    expect(sandbox.exec).toHaveBeenCalledWith("chmod 0755 /workspace/run-review.sh");
    expect(sandbox.startProcess).toHaveBeenCalledTimes(1);
  });

  it("applies the Worker vars when the body is absent", async () => {
    const {sandbox, env, config} = setup({RVW_CODEX_MODEL: "gpt-6-astra", RVW_CODEX_REASONING_EFFORT: "medium"});
    const response = await start(post(START_URL), env, config, new URL(START_URL));
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toMatchObject({model: "gpt-6-astra", reasoning_effort: "medium"});
    expect(runLine(sandbox).endsWith("--json --model 'gpt-6-astra' --reasoning-effort 'medium'")).toBe(true);
  });

  it("lets the body win over the Worker vars field by field", async () => {
    const {sandbox, env, config} = setup({RVW_CODEX_MODEL: "gpt-6-astra", RVW_CODEX_REASONING_EFFORT: "medium"});
    const response = await start(post(START_URL, JSON.stringify({reasoning_effort: "xhigh"})), env, config, new URL(START_URL));
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toMatchObject({model: "gpt-6-astra", reasoning_effort: "xhigh"});
    expect(runLine(sandbox).endsWith("--json --model 'gpt-6-astra' --reasoning-effort 'xhigh'")).toBe(true);

    const other = setup({RVW_CODEX_REASONING_EFFORT: "medium"});
    const only = await start(post(START_URL, JSON.stringify({model: "gpt-7-nova"})), other.env, other.config, new URL(START_URL));
    await expect(only.json()).resolves.toMatchObject({model: "gpt-7-nova", reasoning_effort: "medium"});
    expect(runLine(other.sandbox).endsWith("--json --model 'gpt-7-nova' --reasoning-effort 'medium'")).toBe(true);
  });

  it("shell-quotes a model containing an apostrophe", async () => {
    const {sandbox, env, config} = setup();
    const response = await start(post(START_URL, JSON.stringify({model: "it's"})), env, config, new URL(START_URL));
    expect(response.status).toBe(202);
    expect(runLine(sandbox)).toContain("--model 'it'\\''s'");
  });

  it.each([
    ["an off-enum effort", JSON.stringify({reasoning_effort: "turbo"}), /reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max, ultra, persistent/],
    ["an unknown key", JSON.stringify({model: "gpt-6-astra", effort: "high"}), /unsupported keys: effort/],
    ["an empty model", JSON.stringify({model: " "}), /model must be a non-empty string/],
    ["an array body", JSON.stringify([{model: "gpt-6-astra"}]), /JSON object/],
    ["a JSON null body", "null", /JSON object/],
    ["malformed JSON", "{\"model\": ", /start body must be valid JSON/],
    ["a bare string body", "gpt-6-astra", /start body must be valid JSON/],
  ])("answers 400 for %s without creating a sandbox", async (_label, body, pattern) => {
    const {sandbox, env, config} = setup();
    const response = await handleRoute(post(START_URL, body), env, config);
    expect(response.status).toBe(400);
    const payload = await response.json() as {error: string};
    expect(payload.error).toMatch(pattern);
    expect(mocks.sandboxFor).not.toHaveBeenCalled();
    expect(mocks.configureOutbound).not.toHaveBeenCalled();
    expect(sandbox.startProcess).not.toHaveBeenCalled();
    expect(sandbox.writeFile).not.toHaveBeenCalled();
  });

  it("still requires repo and target as query parameters", async () => {
    const {sandbox, env, config} = setup();
    const missing = await handleRoute(post(`https://worker.example/start?repo=${REPO}`, JSON.stringify({model: "gpt-6-astra"})), env, config);
    expect(missing.status).toBe(400);
    const unsafe = await handleRoute(post(`https://worker.example/start?repo=${REPO}&target=MOVING`), env, config);
    expect(unsafe.status).toBe(400);
    expect(mocks.sandboxFor).not.toHaveBeenCalled();
    expect(sandbox.startProcess).not.toHaveBeenCalled();
  });

  it("keeps the endpoints disabled outside the spike environment", async () => {
    const {env, config} = setup();
    const response = await handleRoute(post(START_URL, JSON.stringify({model: "gpt-6-astra"})), {...env, RVW_ENV: "prod"} as unknown as Env, config);
    expect(response.status).toBe(404);
    expect(mocks.sandboxFor).not.toHaveBeenCalled();
  });
});
