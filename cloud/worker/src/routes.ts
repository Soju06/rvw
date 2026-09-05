import {artifactManifest, artifactPath} from "./artifacts";
import type {RequiredConfig} from "./config";
import {configureOutbound, optionalFile, processPayload, sandboxFor} from "./sandbox";
import {
  buildSandboxProcessEnv,
  validateTargetInput,
} from "./spike-contract";

const MAX_LOG_CHARS = 24_000;

function reviewScript(repoUrl: string, targetSha: string): string { return String.raw`#!/usr/bin/env bash
set -u
LOG=/workspace/rvw-a0.log
RESULT=/workspace/result
TARGET=/workspace/target
mkdir -p "$RESULT"
exec > >(tee -a "$LOG") 2>&1
printf 'A0_PROCESS_FIRST_LOG_TS=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
printf 'A0_REVIEW_TARGET=%s\n' '${targetSha}'
printf 'A0_RUN_STARTED_EPOCH_MS=%s\n' "$(date +%s%3N)"
python --version; rvw --version; codex --version; node --version; git --version; rg --version | head -1; gh --version | head -1
rvw lanes list
unset RVW_CODEX_DEFAULT_BASE_URL RVW_CODEX_SANDBOX
printenv | grep -i -E 'codex|api_key|token' | sort | tee "$RESULT/credential-env.txt"
python -m rvw.container_entrypoint --version
sed -E 's/(CODEX_API_KEY|api_key|token)[^[:space:]]*/\1=[REDACTED]/Ig' /root/.codex/config.toml | tee "$RESULT/codex-config-sanitized.toml"
set +e
timeout 180s env RVW_CODEX_SANDBOX=read-only codex exec --sandbox read-only --skip-git-repo-check 'Reply with exactly CF_SANDBOX_PROBE_OK. Do not modify any files.' > "$RESULT/inner-sandbox-probe.txt" 2>&1
probe_rc=$?
printf '%s\n' "$probe_rc" > "$RESULT/inner-sandbox-probe-exit-code.txt"
set -e
git clone '${repoUrl}' "$TARGET"; git -C "$TARGET" checkout --detach '${targetSha}'
cd "$TARGET"
set +e
env RVW_CODEX_SANDBOX=danger-full-access python -m rvw.container_entrypoint run --target '${targetSha}' --repo-dir "$TARGET" --out "$RESULT" --policy auto --publish none --json
review_rc=$?
printf 'A0_REVIEW_EXIT_CODE=%s\n' "$review_rc"
printf 'A0_RUN_FINISHED_EPOCH_MS=%s\n' "$(date +%s%3N)"
printf '%s\n' "$review_rc" > /workspace/process-exit-code
exit "$review_rc"
`; }

function json(value: unknown, init?: ResponseInit): Response { return Response.json(value, init); }
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function required(url: URL, key: string): string | null { return url.searchParams.get(key); }

export async function start(env: Env, config: RequiredConfig, url: URL): Promise<Response> {
  const target = validateTargetInput(required(url, "repo"), required(url, "target"));
  if (!target) return json({error: "repo must be a safe HTTPS GitHub repository URL and target must be 7-40 lowercase hexadecimal characters"}, {status: 400});
  const sandboxId = `rvw-spike-${crypto.randomUUID()}`;
  const sandbox = sandboxFor(env, sandboxId);
  await configureOutbound(sandbox, config.codexProxyHost);
  await sandbox.writeFile("/workspace/run-review.sh", reviewScript(target.repoUrl, target.targetSha));
  await sandbox.exec("chmod 0755 /workspace/run-review.sh");
  const process = await sandbox.startProcess("/workspace/run-review.sh", {env: buildSandboxProcessEnv(config.codexProxyHost)});
  return json({sandboxId, processId: process.id, repo: target.repoUrl, target: target.targetSha}, {status: 202});
}

export async function status(env: Env, url: URL): Promise<Response> {
  const sandboxId = required(url, "sandboxId");
  const processId = required(url, "processId");
  if (!sandboxId || !processId) return json({error: "sandboxId and processId are required"}, {status: 400});
  const sandbox = sandboxFor(env, sandboxId);
  const process = await sandbox.getProcess(processId);
  let logs = {stdout: "", stderr: ""};
  try { logs = await sandbox.getProcessLogs(processId); } catch (error) { logs.stderr = `getProcessLogs failed: ${errorMessage(error)}`; }
  const marker = await optionalFile(sandbox, "/workspace/process-exit-code");
  return json({sandboxId, process: processPayload(process), marker: marker ? {exitCode: Number.parseInt(marker.trim(), 10)} : null, logTail: {stdout: logs.stdout.slice(-MAX_LOG_CHARS), stderr: logs.stderr.slice(-MAX_LOG_CHARS)}, observedAt: new Date().toISOString()});
}

export async function result(env: Env, url: URL): Promise<Response> {
  const sandboxId = required(url, "sandboxId");
  if (!sandboxId) return json({error: "sandboxId is required"}, {status: 400});
  const sandbox = sandboxFor(env, sandboxId);
  const artifacts: Record<string, string | null> = {};
  const processJson = await optionalFile(sandbox, artifactPath("process.json"));
  if (processJson !== null) {
    for (const {path} of artifactManifest(processJson)) {
      artifacts[path] = await optionalFile(sandbox, artifactPath(path));
    }
  }
  artifacts["process-exit-code"] = await optionalFile(sandbox, "/workspace/process-exit-code");
  return json({sandboxId, artifacts, observedAt: new Date().toISOString()});
}

export async function destroy(env: Env, url: URL): Promise<Response> {
  const sandboxId = required(url, "sandboxId");
  if (!sandboxId) return json({error: "sandboxId is required"}, {status: 400});
  await sandboxFor(env, sandboxId).destroy();
  return json({sandboxId, destroyed: true, observedAt: new Date().toISOString()});
}

export function handleRoute(
  request: Request,
  env: Env,
  config: RequiredConfig,
): Promise<Response> | Response {
  const url = new URL(request.url);
  if (env.RVW_ENV !== "spike") return json({error: "not found"}, {status: 404});
  try {
    if (request.method === "POST" && url.pathname === "/start") return start(env, config, url);
    if (request.method === "GET" && url.pathname === "/status") return status(env, url);
    if (request.method === "GET" && url.pathname === "/result") return result(env, url);
    if (request.method === "POST" && url.pathname === "/destroy") return destroy(env, url);
  } catch (error) { return json({error: errorMessage(error)}, {status: 500}); }
  return json({error: "not found"}, {status: 404});
}
