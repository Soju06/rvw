import {defaultPresentation, parsePresentationYaml, type PresentationConfig} from "./presentation";
import {t} from "./i18n";
import type {CheckConclusion} from "./review-job-contract";
import {defaultTriggersPolicy, parseTriggersYaml, type TriggerFacts, type TriggersPolicy} from "./triggers";

const GITHUB_API = "https://api.github.com";
const GITHUB_API_VERSION = "2022-11-28";
const TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1_000;

export type GitHubFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface TokenStorage {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
  delete?(key: string): Promise<boolean>;
}

interface CachedInstallationToken {
  token: string;
  expiresAtMs: number;
}

export class GitHubApiError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(operation: string, status: number) {
    super(`GitHub ${operation} failed with HTTP ${status}`);
    this.name = "GitHubApiError";
    this.status = status;
    this.retryable = status === 408 || status === 429 || status >= 500;
  }
}

function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((size, part) => size + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function derLength(length: number): Uint8Array {
  if (length < 0x80) return Uint8Array.of(length);
  const bytes: number[] = [];
  let remaining = length;
  while (remaining > 0) {
    bytes.unshift(remaining & 0xff);
    remaining >>>= 8;
  }
  return Uint8Array.of(0x80 | bytes.length, ...bytes);
}

function der(tag: number, content: Uint8Array): Uint8Array {
  return concatBytes(Uint8Array.of(tag), derLength(content.length), content);
}

function pkcs1ToPkcs8(pkcs1: Uint8Array): Uint8Array {
  const version = Uint8Array.of(0x02, 0x01, 0x00);
  const rsaAlgorithm = Uint8Array.of(
    0x30,
    0x0d,
    0x06,
    0x09,
    0x2a,
    0x86,
    0x48,
    0x86,
    0xf7,
    0x0d,
    0x01,
    0x01,
    0x01,
    0x05,
    0x00,
  );
  return der(0x30, concatBytes(version, rsaAlgorithm, der(0x04, pkcs1)));
}

function decodePem(privateKey: string): Uint8Array {
  const isPkcs1 = privateKey.includes("-----BEGIN RSA PRIVATE KEY-----");
  const body = privateKey
    .replace(/-----BEGIN (?:RSA )?PRIVATE KEY-----/g, "")
    .replace(/-----END (?:RSA )?PRIVATE KEY-----/g, "")
    .replace(/\s/g, "");
  if (body.length === 0) throw new Error("GitHub App private key is empty or malformed");
  let binary: string;
  try {
    binary = atob(body);
  } catch (error) {
    throw new Error("GitHub App private key is not valid PEM", {cause: error});
  }
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return isPkcs1 ? pkcs1ToPkcs8(bytes) : bytes;
}

function base64Url(input: string | Uint8Array): string {
  const bytes =
    typeof input === "string"
      ? new TextEncoder().encode(input)
      : input;
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

export async function createAppJwt(
  appId: string,
  privateKey: string,
  nowMs = Date.now(),
): Promise<string> {
  const nowSeconds = Math.floor(nowMs / 1_000);
  const header = base64Url(JSON.stringify({alg: "RS256", typ: "JWT"}));
  const payload = base64Url(
    JSON.stringify({iat: nowSeconds - 60, exp: nowSeconds + 540, iss: appId}),
  );
  const signingInput = `${header}.${payload}`;
  const keyData = Uint8Array.from(decodePem(privateKey)).buffer;
  const key = await crypto.subtle.importKey(
    "pkcs8",
    keyData,
    {name: "RSASSA-PKCS1-v1_5", hash: "SHA-256"},
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(signingInput),
  );
  return `${signingInput}.${base64Url(new Uint8Array(signature))}`;
}

function githubHeaders(token: string): Headers {
  return new Headers({
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "User-Agent": "rvw-cloud",
    "X-GitHub-Api-Version": GITHUB_API_VERSION,
  });
}

async function githubJson(
  operation: string,
  path: string,
  token: string,
  init: RequestInit,
  fetcher: GitHubFetch,
): Promise<unknown> {
  const response = await fetcher(`${GITHUB_API}${path}`, {
    ...init,
    headers: githubHeaders(token),
  });
  if (!response.ok) throw new GitHubApiError(operation, response.status);
  return await response.json();
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`GitHub ${label} response must be an object`);
  }
  return value as Record<string, unknown>;
}

function tokenCacheKey(installationId: number, repoId: number, issuesWrite = false): string {
  return `github-token:${installationId}:${repoId}${issuesWrite ? ":issues-write" : ""}`;
}

export interface InstallationTokenOptions {
  storage: TokenStorage;
  appId: string;
  privateKey: string;
  installationId: number;
  repoId: number;
  nowMs?: number;
  fetcher?: GitHubFetch;
  /** Optional only: older installations must keep working before Issues permission approval. */
  issuesWrite?: boolean;
}

export async function getInstallationToken(
  options: InstallationTokenOptions,
): Promise<string> {
  const nowMs = options.nowMs ?? Date.now();
  const key = tokenCacheKey(options.installationId, options.repoId, options.issuesWrite);
  const cached = await options.storage.get<CachedInstallationToken>(key);
  if (
    cached !== undefined &&
    typeof cached.token === "string" &&
    typeof cached.expiresAtMs === "number" &&
    nowMs < cached.expiresAtMs - TOKEN_REFRESH_MARGIN_MS
  ) {
    return cached.token;
  }

  const jwt = await createAppJwt(options.appId, options.privateKey, nowMs);
  let value: unknown;
  try {
    value = await githubJson(
      "installation token exchange",
      `/app/installations/${options.installationId}/access_tokens`,
      jwt,
      {
        method: "POST",
        body: JSON.stringify({
          repository_ids: [options.repoId],
          permissions: {checks: "write", contents: "read", pull_requests: "write",
            ...(options.issuesWrite ? {issues: "write"} : {})},
        }),
      },
      options.fetcher ?? fetch,
    );
  } catch (error) {
    if (options.issuesWrite && error instanceof GitHubApiError && [403, 422].includes(error.status)) {
      console.log(JSON.stringify({event: "mention_reaction_permission_unavailable", installationId: options.installationId,
        repoId: options.repoId, status: error.status}));
      return await getInstallationToken({...options, issuesWrite: false});
    }
    throw error;
  }
  const response = objectValue(value, "installation token");
  if (typeof response.token !== "string" || typeof response.expires_at !== "string") {
    throw new Error("GitHub installation token response is missing token or expires_at");
  }
  const expiresAtMs = Date.parse(response.expires_at);
  if (!Number.isFinite(expiresAtMs) || expiresAtMs <= nowMs) {
    throw new Error("GitHub installation token response has an invalid expiry");
  }
  await options.storage.put<CachedInstallationToken>(key, {
    token: response.token,
    expiresAtMs,
  });
  return response.token;
}

export async function getCloneToken(options: InstallationTokenOptions): Promise<string> {
  return await getInstallationToken(options);
}

export async function clearInstallationToken(
  storage: TokenStorage,
  installationId: number,
  repoId: number,
): Promise<void> {
  if (storage.delete !== undefined) {
    await storage.delete(tokenCacheKey(installationId, repoId));
    await storage.delete(tokenCacheKey(installationId, repoId, true));
  }
}

export interface AuthenticatedApp {
  id: number;
  slug: string;
}

const APP_IDENTITY_TTL_MS = 5 * 60_000;
// Only authenticated public metadata persists across webhook requests. Installation
// tokens remain in their existing scoped storage, and JWTs/private keys are not cached.
const appIdentities = new Map<string, AuthenticatedApp & {expiresAtMs: number}>();
const appIdentityRequests = new Map<string, Promise<AuthenticatedApp>>();

/** Expired metadata cannot reject a candidate before its identity refresh. */
export function getCachedAuthenticatedApp(appId: string, nowMs = Date.now()): AuthenticatedApp | undefined {
  const cached = appIdentities.get(appId);
  return cached === undefined || cached.expiresAtMs <= nowMs ? undefined : {id: cached.id, slug: cached.slug};
}

/** The authenticated App is known before any review/check exists. */
export async function getAuthenticatedApp(options: {
  appId: string; privateKey: string; nowMs?: number; fetcher?: GitHubFetch;
}): Promise<AuthenticatedApp> {
  const nowMs = options.nowMs ?? Date.now();
  const cached = appIdentities.get(options.appId);
  if (cached !== undefined && cached.expiresAtMs > nowMs) return {id: cached.id, slug: cached.slug};
  const pending = appIdentityRequests.get(options.appId);
  if (pending !== undefined) return await pending;
  const request = (async () => {
    const jwt = await createAppJwt(options.appId, options.privateKey, nowMs);
    const response = objectValue(await githubJson("App identity", "/app", jwt, {method: "GET"}, options.fetcher ?? fetch), "App identity");
    if (typeof response.id !== "number" || !Number.isSafeInteger(response.id) || response.id <= 0 ||
        String(response.id) !== options.appId || typeof response.slug !== "string" ||
        !/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(response.slug)) throw new Error("GitHub App identity is invalid");
    const app = {id: response.id, slug: response.slug};
    appIdentities.set(options.appId, {...app, expiresAtMs: nowMs + APP_IDENTITY_TTL_MS});
    return app;
  })();
  appIdentityRequests.set(options.appId, request);
  try { return await request; }
  finally { appIdentityRequests.delete(options.appId); }
}

export interface PullRequestMetadata {
  state: "open" | "closed";
  number: number;
  head: {sha: string; ref: string};
  base: {sha: string; ref: string};
  draft: boolean;
  user: {login: string};
  labels: {name: string}[];
  title: string;
}

export async function getPullRequestMetadata(token: string,
  input: {owner: string; repo: string; prNumber: number}, fetcher: GitHubFetch = fetch,
): Promise<PullRequestMetadata> {
  const response = objectValue(await githubJson("pull request read",
    `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/pulls/${input.prNumber}`,
    token, {method: "GET"}, fetcher), "pull request");
  const ref = (value: unknown): {sha: string; ref: string} => {
    const branch = objectValue(value, "pull request ref");
    if (typeof branch.sha !== "string" || !/^[a-f0-9]{40}$/i.test(branch.sha) ||
        typeof branch.ref !== "string" || branch.ref.length === 0) throw new Error("GitHub pull request ref is invalid");
    return {sha: branch.sha, ref: branch.ref};
  };
  const user = objectValue(response.user, "pull request user");
  if ((response.state !== "open" && response.state !== "closed") || response.number !== input.prNumber ||
      typeof response.draft !== "boolean" || typeof response.title !== "string" ||
      typeof user.login !== "string" || user.login.length === 0 || !Array.isArray(response.labels)) {
    throw new Error("GitHub pull request metadata is invalid");
  }
  const labels = response.labels.map((entry) => {
    const label = objectValue(entry, "pull request label");
    if (typeof label.name !== "string") throw new Error("GitHub pull request label is invalid");
    return {name: label.name};
  });
  return {state: response.state, number: input.prNumber, head: ref(response.head), base: ref(response.base),
    draft: response.draft, user: {login: user.login}, labels, title: response.title};
}

export async function addCommentReaction(token: string,
  input: {owner: string; repo: string; commentId: number; surface: "issue_comment" | "pull_request_review_comment"},
  fetcher: GitHubFetch = fetch,
): Promise<void> {
  const route = input.surface === "issue_comment" ? "issues" : "pulls";
  await githubJson("comment reaction", `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/${route}/comments/${input.commentId}/reactions`,
    token, {method: "POST", body: JSON.stringify({content: "eyes"})}, fetcher);
}

export interface CreateCheckRunInput {
  owner: string;
  repo: string;
  headSha: string;
  jobId: string;
  detailsUrl?: string;
  presentation?: PresentationConfig;
  trigger?: TriggerFacts;
}

export interface CreatedCheckRun {
  id: number;
  htmlUrl?: string;
  /** The App's slug as GitHub reports it on the check run; its bot login is `<slug>[bot]`. */
  appSlug?: string;
}

function appSlugOf(response: Record<string, unknown>): string | undefined {
  const app = response.app;
  if (typeof app !== "object" || app === null || Array.isArray(app)) return undefined;
  const slug = (app as Record<string, unknown>).slug;
  return typeof slug === "string" && /^[A-Za-z0-9][A-Za-z0-9-]*$/.test(slug) ? slug : undefined;
}

export async function createCheckRun(
  token: string,
  input: CreateCheckRunInput,
  fetcher: GitHubFetch = fetch,
): Promise<CreatedCheckRun> {
  const presentation = input.presentation ?? defaultPresentation();
  const value = await githubJson(
    "Check Run creation",
    `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/check-runs`,
    token,
    {
      method: "POST",
      body: JSON.stringify({
        name: presentation.short_name,
        head_sha: input.headSha,
        status: "in_progress",
        external_id: input.jobId,
        started_at: new Date().toISOString(),
        ...(input.detailsUrl === undefined ? {} : {details_url: input.detailsUrl}),
        output: {title: t("check_started", presentation.locale, {display_name: presentation.display_name}),
          summary: t("bootstrap_summary", presentation.locale),
          text: checkDetails({job_id: input.jobId, ...(input.trigger === undefined ? {} : {trigger: input.trigger})}, presentation)},
      }),
    },
    fetcher,
  );
  const response = objectValue(value, "Check Run creation");
  if (typeof response.id !== "number" || !Number.isSafeInteger(response.id)) {
    throw new Error("GitHub Check Run response is missing an integer id");
  }
  if (response.html_url !== undefined && typeof response.html_url !== "string") {
    throw new Error("GitHub Check Run response html_url must be a string");
  }
  const appSlug = appSlugOf(response);
  return {
    id: response.id,
    ...(typeof response.html_url === "string" ? {htmlUrl: response.html_url} : {}),
    ...(appSlug === undefined ? {} : {appSlug}),
  };
}

/** Read the App slug from an existing check run when a job re-enters without it. */
export async function getCheckRunAppSlug(
  token: string,
  input: {owner: string; repo: string; checkRunId: number},
  fetcher: GitHubFetch = fetch,
): Promise<string | undefined> {
  const value = await githubJson(
    "Check Run read",
    `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/check-runs/${input.checkRunId}`,
    token,
    {method: "GET"},
    fetcher,
  );
  return appSlugOf(objectValue(value, "Check Run read"));
}

export interface UpdateCheckRunInput {
  owner: string;
  repo: string;
  checkRunId: number;
  conclusion: CheckConclusion;
  title: string;
  summary: string;
  name?: string;
  text?: string;
}

export async function updateCheckRun(
  token: string,
  input: UpdateCheckRunInput,
  fetcher: GitHubFetch = fetch,
): Promise<void> {
  await githubJson(
    "Check Run update",
    `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/check-runs/${input.checkRunId}`,
    token,
    {
      method: "PATCH",
      body: JSON.stringify({
        status: "completed",
        ...(input.name === undefined ? {} : {name: input.name}),
        conclusion: input.conclusion,
        completed_at: new Date().toISOString(),
        output: {title: input.title, summary: input.summary, ...(input.text === undefined ? {} : {text: input.text})},
      }),
    },
    fetcher,
  );
}

export function checkDetails(facts: Record<string, unknown>, presentation: PresentationConfig): string {
  // Escaping '<' prevents arbitrary diagnostic strings from ending the collapsed section.
  const json = JSON.stringify(facts, null, 2).replace(/</g, "\\u003c");
  const fence = "`".repeat(Math.max(3, ...[...json.matchAll(/`+/g)].map((match) => match[0].length + 1)));
  return `<details><summary>${t("details", presentation.locale)}</summary>\n\n${fence}json\n${json}\n${fence}\n</details>`;
}

export async function getPresentationConfig(
  token: string,
  input: {owner: string; repo: string; baseSha: string},
  fetcher: GitHubFetch = fetch,
): Promise<{presentation: PresentationConfig; failure?: "presentation_config_invalid"}> {
  try {
    const raw = await getBaseRefFile(token, input, ".rvw/config.yaml", fetcher);
    return {presentation: raw === null ? defaultPresentation() : parsePresentationYaml(raw)};
  } catch (error) {
    if (error instanceof GitHubApiError) throw error;
    return {presentation: defaultPresentation(), failure: "presentation_config_invalid"};
  }
}

async function getBaseRefFile(
  token: string,
  input: {owner: string; repo: string; baseSha: string},
  file: ".rvw/config.yaml" | ".rvw/policies/auto.yaml",
  fetcher: GitHubFetch,
): Promise<string | null> {
  const path = `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/contents/${file}?ref=${encodeURIComponent(input.baseSha)}`;
  let response: Response;
  try { response = await fetcher(`${GITHUB_API}${path}`, {method: "GET", headers: githubHeaders(token)}); }
  catch { throw new GitHubApiError(`${file} read`, 503); }
  if (response.status === 404) return null;
  if (!response.ok) throw new GitHubApiError(`${file} read`, response.status);
  const body = objectValue(await response.json(), "base-ref file");
  const maximum = file === ".rvw/config.yaml" ? 32_768 : 131_072;
  if (body.type !== "file" || body.target !== undefined || body.encoding !== "base64" ||
      typeof body.content !== "string" || body.content.length > maximum) throw new Error("invalid base-ref file");
  const bytes = Uint8Array.from(atob(body.content.replace(/\s/g, "")), (character) => character.charCodeAt(0));
  return new TextDecoder("utf-8", {fatal: true}).decode(bytes);
}

export async function getTriggerPolicy(
  token: string,
  input: {owner: string; repo: string; baseSha: string},
  fetcher: GitHubFetch = fetch,
): Promise<{policy: TriggersPolicy; failure?: "policy_invalid"}> {
  try {
    const raw = await getBaseRefFile(token, input, ".rvw/policies/auto.yaml", fetcher);
    return {policy: raw === null ? defaultTriggersPolicy() : parseTriggersYaml(raw)};
  } catch (error) {
    if (error instanceof GitHubApiError) throw error;
    return {policy: defaultTriggersPolicy(), failure: "policy_invalid"};
  }
}

interface HeadChecksInput {
  owner: string;
  repo: string;
  headSha: string;
  appId: string;
}

async function* ownHeadChecks(token: string, input: HeadChecksInput, fetcher: GitHubFetch): AsyncGenerator<Record<string, unknown>> {
  const prefix = `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/commits/${encodeURIComponent(input.headSha)}/check-runs`;
  for (let page = 1; ; page += 1) {
    const result = objectValue(await githubJson("Check Runs read",
      `${prefix}?filter=all&app_id=${encodeURIComponent(input.appId)}&per_page=100&page=${page}`,
      token, {method: "GET"}, fetcher), "Check Runs read");
    if (!Array.isArray(result.check_runs)) throw new Error("GitHub Check Runs response is missing check_runs");
    for (const value of result.check_runs) {
      const check = objectValue(value, "Check Run");
      const app = check.app;
      if (typeof app !== "object" || app === null || Array.isArray(app)) continue;
      const appId = (app as Record<string, unknown>).id;
      if (typeof appId === "number" && Number.isSafeInteger(appId) && appId > 0 && String(appId) === input.appId) yield check;
    }
    if (result.check_runs.length < 100) return;
  }
}

function reviewCheckFacts(check: Record<string, unknown>): Record<string, unknown> | null {
  const output = check.output;
  if (typeof output !== "object" || output === null) return null;
  const text = (output as Record<string, unknown>).text;
  if (typeof text !== "string") return null;
  const json = /(?:^|\n)(`{3,})json\n([\s\S]*?)\n\1(?:\n|$)/.exec(text);
  if (json === null) return null;
  try { return objectValue(JSON.parse(json[2]), "review facts"); } catch { return null; }
}

/** Job identities, unlike GitHub commit/branch PR associations, identify reviewed work. */
function reviewJobId(value: unknown): string | null {
  return typeof value === "string" && /^[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*:[0-9a-f]{40}$/.test(value)
    ? value : null;
}

/** A neutral policy check or infrastructure result is not completed review work. */
export async function hasCompletedReviewForHead(token: string,
  input: HeadChecksInput & {installationId: number; repoId: number; prNumber: number},
  fetcher: GitHubFetch = fetch,
): Promise<boolean> {
  const jobId = `${input.installationId}:${input.repoId}:${input.prNumber}:${input.headSha}`;
  for await (const check of ownHeadChecks(token, input, fetcher)) {
    if (check.head_sha !== input.headSha || check.status !== "completed" ||
        typeof check.external_id !== "string" || check.external_id.endsWith(":trigger-skip")) continue;
    const externalJobId = reviewJobId(check.external_id);
    if (externalJobId !== null && externalJobId !== jobId) continue;
    const facts = reviewCheckFacts(check);
    if (facts === null) continue;
    const artifactKey = `jobs/${jobId}/`;
    // Embedded identities must agree with the requested job, including when the
    // explicit completion marker is present. Association alone is never evidence.
    if (facts.job_id !== undefined && facts.job_id !== jobId) continue;
    if (facts.artifact_key !== undefined && facts.artifact_key !== artifactKey) continue;
    if (externalJobId === null && facts.job_id !== jobId && facts.artifact_key !== artifactKey) continue;
    const trigger = facts.trigger;
    if (typeof trigger === "object" && trigger !== null && (trigger as Record<string, unknown>).skipped) continue;
    if (facts.review_completed === true) return true;
    if (facts.review_completed !== undefined) continue;
    // Legacy checks predate the explicit marker. Require the structured, known terminal
    // process reason and completed lane evidence; the configurable conclusion is insufficient.
    const lanes = facts.lanes;
    if (facts.job_id !== jobId || facts.artifact_key !== artifactKey ||
        typeof lanes !== "object" || lanes === null || typeof (lanes as Record<string, unknown>).valid !== "number" ||
        Number((lanes as Record<string, unknown>).valid) <= 0 || typeof facts.reason !== "string") continue;
    for (const locale of ["en", "ko"] as const) {
      for (const key of ["process_passed", "process_blocked"] as const) {
        const suffix = t(key, locale, {display_name: ""});
        if (facts.reason.endsWith(suffix) && facts.reason.length > suffix.length) return true;
      }
    }
  }
  return false;
}

/** Idempotent neutral outcome for a skipped head; no review job or sandbox is created. */
export async function upsertSkippedCheckRun(
  token: string,
  input: CreateCheckRunInput & {title: string; summary: string; trigger: TriggerFacts; appId: string},
  fetcher: GitHubFetch = fetch,
): Promise<void> {
  const presentation = input.presentation ?? defaultPresentation();
  const prefix = `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}`;
  const externalId = `${input.jobId}:trigger-skip`;
  const text = checkDetails({trigger: input.trigger}, presentation);
  for await (const check of ownHeadChecks(token, input, fetcher)) {
    if (check.external_id === externalId && check.status === "completed" && check.conclusion === "neutral" &&
        typeof check.id === "number") {
      await updateCheckRun(token, {...input, checkRunId: check.id, conclusion: "neutral", text}, fetcher);
      return;
    }
  }
  await githubJson("skipped Check Run creation", `${prefix}/check-runs`, token, {method: "POST", body: JSON.stringify({
    name: presentation.short_name, head_sha: input.headSha, external_id: externalId,
    status: "completed", conclusion: "neutral", completed_at: new Date().toISOString(),
    output: {title: input.title, summary: input.summary, text},
  })}, fetcher);
}
