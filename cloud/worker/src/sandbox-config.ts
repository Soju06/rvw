import {requiredConfig, type ConfigEnvironment} from "./config";
import {injectCodexCredential, type OutboundFetcher} from "./sandbox-auth";

export interface OutboundConfigurable {
  setOutboundByHosts(
    handlers: Record<string, string | {method: string; params: Record<string, unknown>}>,
  ): Promise<unknown>;
  setAllowedHosts(hosts: string[]): Promise<unknown>;
}

/**
 * The only GitHub hosts the review needs: the CLI clones over github.com and resolves
 * and publishes through api.github.com. Together with the Codex proxy host they form the
 * sandbox's HTTP(S) egress allowlist for the whole run; every other host is answered by
 * the Worker proxy with 520, so a model-driven tool command cannot reach arbitrary hosts.
 * The pinned Containers SDK already intercepts all HTTP(S) once runtime outbound overrides
 * exist, and its allowlist gates every proxied request before handler selection.
 */
export const REVIEW_EGRESS_HOSTS = ["api.github.com", "github.com"] as const;

export function reviewEgressAllowlist(proxyHost: string): string[] {
  return [proxyHost, ...REVIEW_EGRESS_HOSTS];
}

interface CodexEnvironment extends ConfigEnvironment {
  CODEX_API_KEY: string;
}

export async function configureCodexEgress(
  sandbox: OutboundConfigurable,
  proxyHost: string,
  installationToken?: string,
): Promise<void> {
  await sandbox.setOutboundByHosts({
    [proxyHost]: "codex",
    ...(installationToken === undefined
      ? {}
      : {
          "api.github.com": {method: "githubApi", params: {token: installationToken}},
          "github.com": {method: "githubClone", params: {token: installationToken}},
        }),
  });
  await sandbox.setAllowedHosts(reviewEgressAllowlist(proxyHost));
}

export async function codexOutboundHandler(
  request: Request,
  env: CodexEnvironment,
  fetcher: OutboundFetcher = fetch,
): Promise<Response> {
  const config = requiredConfig(env);
  const hostname = new URL(request.url).hostname;
  if (hostname !== config.codexProxyHost) {
    throw new Error("outbound host does not match CODEX_PROXY_HOST");
  }
  return await injectCodexCredential(request, env.CODEX_API_KEY, fetcher, ({hostname}) => {
    console.log(JSON.stringify({event: "codex_credential_injected", hostname}));
  });
}
