import type {CheckConclusion} from "./review-job-contract";

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

function tokenCacheKey(installationId: number, repoId: number): string {
  return `github-token:${installationId}:${repoId}`;
}

export interface InstallationTokenOptions {
  storage: TokenStorage;
  appId: string;
  privateKey: string;
  installationId: number;
  repoId: number;
  nowMs?: number;
  fetcher?: GitHubFetch;
}

export async function getInstallationToken(
  options: InstallationTokenOptions,
): Promise<string> {
  const nowMs = options.nowMs ?? Date.now();
  const key = tokenCacheKey(options.installationId, options.repoId);
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
  const value = await githubJson(
    "installation token exchange",
    `/app/installations/${options.installationId}/access_tokens`,
    jwt,
    {
      method: "POST",
      body: JSON.stringify({
        repository_ids: [options.repoId],
        permissions: {checks: "write", contents: "read", pull_requests: "write"},
      }),
    },
    options.fetcher ?? fetch,
  );
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
  }
}

export interface CreateCheckRunInput {
  owner: string;
  repo: string;
  headSha: string;
  jobId: string;
  detailsUrl?: string;
}

export interface CreatedCheckRun {
  id: number;
  htmlUrl?: string;
}

export async function createCheckRun(
  token: string,
  input: CreateCheckRunInput,
  fetcher: GitHubFetch = fetch,
): Promise<CreatedCheckRun> {
  const value = await githubJson(
    "Check Run creation",
    `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/check-runs`,
    token,
    {
      method: "POST",
      body: JSON.stringify({
        name: "rvw",
        head_sha: input.headSha,
        status: "in_progress",
        external_id: input.jobId,
        started_at: new Date().toISOString(),
        ...(input.detailsUrl === undefined ? {} : {details_url: input.detailsUrl}),
        output: {title: "rvw review in progress", summary: `Job ${input.jobId}`},
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
  return {
    id: response.id,
    ...(typeof response.html_url === "string" ? {htmlUrl: response.html_url} : {}),
  };
}

export interface UpdateCheckRunInput {
  owner: string;
  repo: string;
  checkRunId: number;
  conclusion: CheckConclusion;
  title: string;
  summary: string;
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
        conclusion: input.conclusion,
        completed_at: new Date().toISOString(),
        output: {title: input.title, summary: input.summary},
      }),
    },
    fetcher,
  );
}
