import {requiredConfig, type ConfigEnvironment} from "./config";
import {injectCodexCredential, type OutboundFetcher} from "./sandbox-auth";

export interface OutboundConfigurable {
  setOutboundByHosts(
    handlers: Record<string, string | {method: string; params: Record<string, unknown>}>,
  ): Promise<unknown>;
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
