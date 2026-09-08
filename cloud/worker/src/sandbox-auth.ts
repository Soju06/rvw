// This module stays import-free: the Python adapter-parity test loads it directly with Node.

/** The CLI rejects `--deadline` above this ceiling (`MAX_DEADLINE_SECONDS` in dispatch.py). */
export const MAX_REVIEW_DEADLINE_SECONDS = 1800;

/**
 * The named Codex 0.152.0 `ReasoningEffort` variants (codex-rs/protocol/src/openai_models.rs),
 * mirrored by `REASONING_EFFORT_VALUES` in rvw.runtime_policy. Codex also accepts an arbitrary
 * custom string; rvw deliberately does not, so a typo cannot select an unknown effort.
 */
export const REASONING_EFFORT_VALUES = [
  "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent",
] as const;
export type ReasoningEffort = (typeof REASONING_EFFORT_VALUES)[number];
const REASONING_EFFORTS: ReadonlySet<string> = new Set<string>(REASONING_EFFORT_VALUES);

export function isReasoningEffort(value: unknown): value is ReasoningEffort {
  return typeof value === "string" && REASONING_EFFORTS.has(value);
}

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

export type ReviewProcessEnv = Record<"CODEX_API_KEY" | "CODEX_BASE_URL", string> &
  Partial<Record<"RVW_GITHUB_LOGIN", string>>;

/**
 * Build the review process environment. `githubLogin` is the App's own bot login
 * (`<slug>[bot]`); an installation token cannot describe itself, so Python needs it to
 * recognise, reuse, and resolve its own review threads. It travels through the process
 * environment, not the script, because the script unsets unrelated variables before exec.
 */
export function buildReviewProcessEnv(proxyHost: string, githubLogin?: string): ReviewProcessEnv {
  return {
    CODEX_API_KEY: "placeholder-not-a-secret",
    CODEX_BASE_URL: `https://${proxyHost}/backend-api/codex`,
    ...(githubLogin === undefined || githubLogin.length === 0 ? {} : {RVW_GITHUB_LOGIN: githubLogin}),
  };
}

/** GitHub names an App's actor `<slug>[bot]` in REST; Python strips the suffix for GraphQL. */
export function botLoginForAppSlug(slug: string): string {
  return `${slug}[bot]`;
}

/** Quote one shell argument; callers may safely pass paths containing apostrophes. */
export function shellQuote(value: string): string {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

export interface ReviewInvocation {
  owner: string;
  repo: string;
  prNumber: number;
  baseSha: string;
  headSha: string;
  out?: string;
  repoDir?: string;
  /**
   * `github-review` is canonical: the Python side selects the review event from the
   * repository policy. `github-comment` is the deprecated alias accepted for one release.
   */
  publish?: "none" | "github-review" | "github-comment";
  /** Explicit runtime deadline in seconds; the CLI default is never relied upon. */
  deadlineSeconds: number;
  /** Codex model override (`--model`); absent keeps the packaged CLI default. */
  model?: string;
  /** Codex reasoning effort override (`--reasoning-effort`); absent keeps the packaged CLI default. */
  reasoningEffort?: string;
}

/**
 * Render the optional `--model` / `--reasoning-effort` overrides, each only when supplied.
 * The CLI resolves explicit option > environment variable > packaged default, so an absent
 * flag leaves the container's own resolution untouched.
 */
export function codexPolicyArguments(model: string | undefined, reasoningEffort: string | undefined): string {
  let rendered = "";
  if (model !== undefined) {
    if (typeof model !== "string" || model.trim().length === 0) {
      throw new Error("Codex model override must be a non-empty string");
    }
    rendered += ` --model ${shellQuote(model)}`;
  }
  if (reasoningEffort !== undefined) {
    if (!isReasoningEffort(reasoningEffort)) {
      throw new Error(`Codex reasoning effort override must be one of: ${REASONING_EFFORT_VALUES.join(", ")}`);
    }
    rendered += ` --reasoning-effort ${shellQuote(reasoningEffort)}`;
  }
  return rendered;
}

export function buildRvwRunInvocation(options: ReviewInvocation): string {
  const {owner, repo, prNumber, baseSha, headSha} = options;
  if (!REPOSITORY_PART.test(owner) || !REPOSITORY_PART.test(repo)) {
    throw new Error("GitHub owner and repository must be safe path components");
  }
  if (!Number.isSafeInteger(prNumber) || prNumber <= 0) {
    throw new Error("pull-request number must be a positive integer");
  }
  if (!/^[0-9a-f]{40}$/.test(baseSha) || !/^[0-9a-f]{40}$/.test(headSha)) {
    throw new Error("pull-request anchors must be full commit SHAs");
  }
  const {deadlineSeconds} = options;
  if (!Number.isSafeInteger(deadlineSeconds) || deadlineSeconds < 1 || deadlineSeconds > MAX_REVIEW_DEADLINE_SECONDS) {
    throw new Error(`review deadline must be an integer between 1 and ${MAX_REVIEW_DEADLINE_SECONDS} seconds`);
  }
  const policyArguments = codexPolicyArguments(options.model, options.reasoningEffort);
  return (
    "env RVW_CODEX_SANDBOX=danger-full-access python -m rvw.container_entrypoint run " +
    `--target ${shellQuote(`https://github.com/${owner}/${repo}/pull/${prNumber}`)} ` +
    `--base-ref ${shellQuote(baseSha)} --head-ref ${shellQuote(headSha)} ` +
    `--out ${shellQuote(options.out ?? "/workspace/result")} ` +
    (options.repoDir === undefined ? "" : `--repo-dir ${shellQuote(options.repoDir)} `) +
    `--deadline ${deadlineSeconds} --policy auto --publish ${options.publish ?? "github-review"} --json` +
    policyArguments
  );
}
