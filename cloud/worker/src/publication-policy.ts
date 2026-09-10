import {isScalar, parseDocument, type ParsedNode} from "yaml";

import type {GitHubFetch} from "./github-app";

const GITHUB_API = "https://api.github.com";
const GITHUB_API_VERSION = "2022-11-28";

export type PublishChannel = "checks" | "review";
export interface CheckPublicationPolicy {
  on_block: "failure" | "neutral";
  on_pass: "success" | "neutral";
}
export interface InlinePublicationPolicy {
  severity_at_least: "suggestion" | "warning" | "blocker";
  max_comments: number | null;
}
export interface PublicationPolicy {
  channels: PublishChannel[];
  checks: CheckPublicationPolicy;
  inline: InlinePublicationPolicy;
}

export function defaultPublicationPolicy(): PublicationPolicy {
  return {
    channels: ["checks", "review"],
    checks: {on_block: "failure", on_pass: "success"},
    inline: {severity_at_least: "suggestion", max_comments: null},
  };
}

/** A malformed publication policy must never enable a GitHub review write. */
export function conservativePublicationPolicy(): PublicationPolicy {
  return {...defaultPublicationPolicy(), channels: ["checks"]};
}

function invalid(detail: string): never {
  throw new Error(`publish_policy_invalid: ${detail}`);
}

function mapping(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid(`${label} must be a mapping`);
  return value as Record<string, unknown>;
}

function requiredPublishState(value: unknown): "comment" | "none" {
  if (value !== "comment" && value !== "none") invalid("publish_state is invalid");
  return value;
}

function fields(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const extra = Object.keys(value).find((key) => !allowed.includes(key));
  if (extra !== undefined) invalid(`${label}.${extra} is unsupported`);
}

function strictBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") invalid(`${label} must be a boolean`);
  return value;
}

function parseChecks(value: unknown): CheckPublicationPolicy {
  if (value === undefined) return defaultPublicationPolicy().checks;
  const record = mapping(value, "publish.checks");
  fields(record, ["on_block", "on_pass"], "publish.checks");
  const onBlock = record.on_block === undefined ? "failure" : record.on_block;
  const onPass = record.on_pass === undefined ? "success" : record.on_pass;
  if (onBlock !== "failure" && onBlock !== "neutral") invalid("publish.checks.on_block is invalid");
  if (onPass !== "success" && onPass !== "neutral") invalid("publish.checks.on_pass is invalid");
  return {on_block: onBlock, on_pass: onPass};
}

function parseInline(value: unknown, maximumNode: ParsedNode | null | undefined): InlinePublicationPolicy {
  if (value === undefined) return defaultPublicationPolicy().inline;
  const record = mapping(value, "publish.inline");
  fields(record, ["severity_at_least", "max_comments"], "publish.inline");
  const severity = record.severity_at_least === undefined ? "suggestion" : record.severity_at_least;
  const maximum = record.max_comments === undefined ? null : record.max_comments;
  if (!(["suggestion", "warning", "blocker"] as unknown[]).includes(severity)) {
    invalid("publish.inline.severity_at_least is invalid");
  }
  const integerScalar = isScalar(maximumNode) && typeof maximumNode.value === "number" &&
    (maximumNode.format === "BIN" || maximumNode.format === "OCT" || maximumNode.format === "HEX" ||
      maximumNode.format === "TIME" || !/[.eE]/.test(maximumNode.source ?? ""));
  const integerMaximum = typeof maximum === "number" && Number.isSafeInteger(maximum) && maximum >= 0;
  if (!(maximum === null || (integerScalar && integerMaximum))) {
    invalid("publish.inline.max_comments must be a non-negative integer or null");
  }
  return {severity_at_least: severity as InlinePublicationPolicy["severity_at_least"], max_comments: maximum as number | null};
}

function parseChannels(value: unknown): PublishChannel[] {
  if (!Array.isArray(value) || value.length === 0 ||
      value.some((channel) => channel !== "checks" && channel !== "review")) {
    invalid("publish.channels must be a nonempty list of checks or review");
  }
  return value as PublishChannel[];
}

function validateReviewControls(record: Record<string, unknown>): void {
  const onBlock = record.on_block === undefined ? "comment" : record.on_block;
  const onPass = record.on_pass === undefined ? "comment" : record.on_pass;
  const dismiss = record.dismiss_on_pass === undefined ? false : record.dismiss_on_pass;
  const approvalGate = record.approve_requires_explicit_opt_in === undefined
    ? true : record.approve_requires_explicit_opt_in;
  if (onBlock !== "comment" && onBlock !== "request_changes") invalid("publish.on_block is invalid");
  if (onPass !== "comment" && onPass !== "approve" && onPass !== "none") invalid("publish.on_pass is invalid");
  strictBoolean(dismiss, "publish.dismiss_on_pass");
  strictBoolean(approvalGate, "publish.approve_requires_explicit_opt_in");
  if (onPass === "approve" && approvalGate) invalid("approve_not_opted_in");
}

function validateThreads(value: unknown): void {
  if (value === undefined) return;
  const record = mapping(value, "threads");
  fields(record, ["resolve_on_fix", "reuse_open_thread"], "threads");
  if (record.resolve_on_fix !== undefined) strictBoolean(record.resolve_on_fix, "threads.resolve_on_fix");
  if (record.reuse_open_thread !== undefined) strictBoolean(record.reuse_open_thread, "threads.reuse_open_thread");
}

/** Parse the strict publication subset of a repository auto policy. */
export function parsePublicationPolicyYaml(raw: string, maximumCharacters = 32_768): PublicationPolicy {
  try {
    if (raw.length > maximumCharacters) invalid("policy file is too large");
    // PyYAML, used by Python's authoritative reader, follows YAML 1.1 scalar coercion.
    const document = parseDocument(raw, {schema: "yaml-1.1", uniqueKeys: true});
    if (document.errors.length > 0) invalid(document.errors[0].message);
    const root = mapping(document.toJS(), "policy");
    const publishState = requiredPublishState(root.publish_state);
    validateThreads(root.threads);
    if (root.publish === undefined) {
      return publishState === "none"
        ? {...defaultPublicationPolicy(), channels: ["checks"]}
        : defaultPublicationPolicy();
    }
    const publish = mapping(root.publish, "publish");
    fields(publish, ["channels", "checks", "inline", "on_block", "on_pass", "dismiss_on_pass",
      "approve_requires_explicit_opt_in"], "publish");
    validateReviewControls(publish);
    return {
      channels: publish.channels === undefined
        ? (publishState === "none" ? ["checks"] : ["checks", "review"])
        : parseChannels(publish.channels),
      checks: parseChecks(publish.checks),
      inline: parseInline(publish.inline, document.getIn(["publish", "inline", "max_comments"], true) as ParsedNode | null | undefined),
    };
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("publish_policy_invalid:")) throw error;
    invalid(error instanceof Error ? error.message : String(error));
  }
}

function githubHeaders(token: string): Headers {
  return new Headers({
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": GITHUB_API_VERSION,
    "User-Agent": "rvw-cloud",
  });
}

export async function getPublicationPolicy(
  token: string,
  input: {owner: string; repo: string; baseSha: string},
  fetcher: GitHubFetch = fetch,
): Promise<{policy: PublicationPolicy; failure?: "publish_policy_invalid"}> {
  const path = `/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}` +
    `/contents/.rvw/policies/auto.yaml?ref=${encodeURIComponent(input.baseSha)}`;
  const response = await fetcher(`${GITHUB_API}${path}`, {method: "GET", headers: githubHeaders(token)});
  if (response.status === 404) return {policy: defaultPublicationPolicy()};
  if (!response.ok) throw new Error(`GitHub publication policy read failed with HTTP ${response.status}`);
  try {
    const body = mapping(await response.json(), "policy response");
    if (body.type !== "file" || body.target !== undefined || body.encoding !== "base64" ||
        typeof body.content !== "string" || body.content.length > 65_536) invalid("policy response is invalid");
    const bytes = Uint8Array.from(atob(body.content.replace(/\s/g, "")), (character) => character.charCodeAt(0));
    const raw = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
    return {policy: parsePublicationPolicyYaml(raw)};
  } catch {
    return {policy: conservativePublicationPolicy(), failure: "publish_policy_invalid"};
  }
}
