import {ContainerProxy, Sandbox, getSandbox, type Process} from "@cloudflare/sandbox";

import {
  injectGitHubApiCredential,
  injectGitHubCloneCredential,
} from "./sandbox-auth";
import {codexOutboundHandler, configureCodexEgress} from "./sandbox-config";

export {ContainerProxy};

export class RvwSandbox extends Sandbox<Env> {
  // A0 measured that @cloudflare/containers 0.3.7 defaults this off, so HTTPS
  // bypasses outboundByHost and the Codex proxy returns 401 unless it is explicit.
  interceptHttps = true;
}

function tokenFromContext(context: {params?: unknown}): string {
  if (typeof context.params !== "object" || context.params === null) {
    throw new Error("GitHub outbound handler token parameters are missing");
  }
  const token = (context.params as Record<string, unknown>).token;
  if (typeof token !== "string" || token.length === 0) {
    throw new Error("GitHub outbound handler token is missing");
  }
  return token;
}

RvwSandbox.outboundHandlers = {
  codex: (request: Request, env: Cloudflare.Env) => codexOutboundHandler(request, env),
  githubApi: (request: Request, _env: Env, context: {params?: unknown}) =>
    injectGitHubApiCredential(request, tokenFromContext(context)),
  githubClone: (request: Request, _env: Env, context: {params?: unknown}) =>
    injectGitHubCloneCredential(request, tokenFromContext(context)),
};

export async function configureOutbound(
  sandbox: RvwSandbox,
  proxyHost: string,
  installationToken?: string,
): Promise<void> {
  await configureCodexEgress(sandbox, proxyHost, installationToken);
}

export function sandboxFor(env: Env, sandboxId: string): RvwSandbox {
  return getSandbox(env.RVW_SANDBOX, sandboxId, {keepAlive: true, normalizeId: true, containerTimeouts: {instanceGetTimeoutMS: 120_000, portReadyTimeoutMS: 120_000}});
}

export function processPayload(process: Process | null): Record<string, unknown> | null {
  if (!process) return null;
  return {id: process.id, pid: process.pid, command: process.command, status: process.status, startTime: process.startTime, endTime: process.endTime, exitCode: process.exitCode};
}

export async function optionalFile(sandbox: RvwSandbox, path: string): Promise<string | null> {
  try {
    const file = await sandbox.readFile(path);
    return typeof file.content === "string" ? file.content : null;
  } catch {
    return null;
  }
}
