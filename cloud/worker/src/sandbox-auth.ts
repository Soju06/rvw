export type CredentialKind = "codex" | "github-api" | "github-clone";
export type OutboundFetcher = (request: Request) => Promise<Response>;
export type InjectionLogger = (entry: {event: string; hostname: string}) => void;

const REPOSITORY_PART = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function defaultLogger(entry: {event: string; hostname: string}): void {
  console.log(JSON.stringify(entry));
}

function authenticatedRequest(request: Request, authorization: string): Request {
  const url = new URL(request.url);
  url.username = "";
  url.password = "";
  const authenticated = new Request(url, request);
  authenticated.headers.set("Authorization", authorization);
  return authenticated;
}

async function injectCredential(
  request: Request,
  authorization: string,
  fetcher: OutboundFetcher,
  logger: InjectionLogger,
): Promise<Response> {
  const hostname = new URL(request.url).hostname;
  logger({event: "egress_credential_injected", hostname});
  return await fetcher(authenticatedRequest(request, authorization));
}

function requiredToken(token: string, label: string): string {
  if (typeof token !== "string" || token.length === 0) {
    throw new Error(`${label} credential is unavailable`);
  }
  return token;
}

export function credentialKindForHost(
  hostname: string,
  codexProxyHost: string,
): CredentialKind | null {
  if (hostname === codexProxyHost) return "codex";
  if (hostname === "api.github.com") return "github-api";
  if (hostname === "github.com") return "github-clone";
  return null;
}

export async function injectCodexCredential(
  request: Request,
  token: string,
  fetcher: OutboundFetcher = fetch,
  logger: InjectionLogger = defaultLogger,
): Promise<Response> {
  return await injectCredential(
    request,
    `Bearer ${requiredToken(token, "Codex")}`,
    fetcher,
    logger,
  );
}

export async function injectGitHubApiCredential(
  request: Request,
  token: string,
  fetcher: OutboundFetcher = fetch,
  logger: InjectionLogger = defaultLogger,
): Promise<Response> {
  return await injectCredential(
    request,
    `Bearer ${requiredToken(token, "GitHub API")}`,
    fetcher,
    logger,
  );
}

export async function injectGitHubCloneCredential(
  request: Request,
  token: string,
  fetcher: OutboundFetcher = fetch,
  logger: InjectionLogger = defaultLogger,
): Promise<Response> {
  const cloneToken = requiredToken(token, "GitHub clone");
  return await injectCredential(
    request,
    `Basic ${btoa(`x-access-token:${cloneToken}`)}`,
    fetcher,
    logger,
  );
}

export function buildGitCloneUrl(owner: string, repo: string): string {
  if (!REPOSITORY_PART.test(owner) || !REPOSITORY_PART.test(repo)) {
    throw new Error("GitHub owner and repository must be safe path components");
  }
  return `https://x-access-token@github.com/${owner}/${repo}.git`;
}

export function buildReviewProcessEnv(
  proxyHost: string,
): Record<"CODEX_API_KEY" | "CODEX_BASE_URL", string> {
  return {
    CODEX_API_KEY: "placeholder-not-a-secret",
    CODEX_BASE_URL: `https://${proxyHost}/backend-api/codex`,
  };
}

export function buildRvwAutoInvocation(owner: string, repo: string, prNumber: number): string {
  if (!REPOSITORY_PART.test(owner) || !REPOSITORY_PART.test(repo)) {
    throw new Error("GitHub owner and repository must be safe path components");
  }
  if (!Number.isSafeInteger(prNumber) || prNumber <= 0) {
    throw new Error("pull-request number must be a positive integer");
  }
  return (
    `env GH_REPO='${owner}/${repo}' RVW_CODEX_SANDBOX=danger-full-access ` +
    "python -m rvw.container_entrypoint auto " +
    `--target 'https://github.com/${owner}/${repo}/pull/${prNumber}' ` +
    '--repo-dir "$ADJ" --json'
  );
}
