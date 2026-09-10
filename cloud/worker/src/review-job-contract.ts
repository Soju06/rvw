import {artifactManifest} from "./artifacts";
import {t} from "./i18n";
import {parsePresentation, type PresentationConfig} from "./presentation";
import type {CheckPublicationPolicy, PublishChannel} from "./publication-policy";

export type JobState =
  | "queued"
  | "provisioning"
  | "running"
  | "publishing"
  | "completed"
  | "failed"
  | "timed_out"
  | "superseded";

export type TerminalJobState = Extract<
  JobState,
  "completed" | "failed" | "timed_out" | "superseded"
>;
export type CheckConclusion = "success" | "failure" | "neutral";

const TRANSITIONS: Readonly<Record<JobState, readonly JobState[]>> = {
  queued: ["provisioning", "superseded"],
  provisioning: ["running", "failed", "superseded"],
  running: ["publishing", "failed", "timed_out", "superseded"],
  publishing: ["completed", "failed", "timed_out", "superseded"],
  completed: [],
  failed: [],
  timed_out: [],
  superseded: [],
};

export function canTransition(from: JobState, to: JobState): boolean {
  return TRANSITIONS[from].includes(to);
}

export function isTerminalState(state: JobState): state is TerminalJobState {
  return TRANSITIONS[state].length === 0;
}

export function shouldRestartForRerequest(
  state: JobState,
  previousDeliveryId: string | undefined,
  event: string,
  deliveryId: string,
): boolean {
  return (
    isTerminalState(state) &&
    event === "check_run.rerequested" &&
    previousDeliveryId !== deliveryId
  );
}

export function isDeadlineReached(nowMs: number, deadlineMs: number): boolean {
  return nowMs >= deadlineMs;
}

interface PublicationFacts {
  publication_failure: string | null;
  language_fallback_used: boolean;
}

/** Effective Codex runtime policy recorded by Python; null fields for legacy envelopes. */
export interface RuntimePolicyFacts {
  model: string | null;
  reasoning_effort: string | null;
}

export interface ReviewResultMapping extends Partial<PublicationFacts> {
  terminalState: "completed" | "failed";
  conclusion: CheckConclusion;
  outcome?: "pass" | "block";
  reason: string;
  reasonCode?: string;
  presentation?: PresentationConfig;
  runtime?: RuntimePolicyFacts;
}

export interface ProcessResult extends PublicationFacts {
  schema_version: 1;
  run_id: string;
  status: "pass" | "block" | "invalid" | "infra_failed";
  exit_code: number;
  failure: {code: string; detail: string} | null;
  presentation: PresentationConfig;
  runtime: RuntimePolicyFacts;
}

function recordValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} artifact must be an object`);
  }
  return value as Record<string, unknown>;
}

function fields(value: Record<string, unknown>, names: string[], label: string): void {
  if (Object.keys(value).some((key) => !names.includes(key)) || names.some((key) => !(key in value))) {
    throw new Error(`${label} artifact fields are missing or unsupported`);
  }
}

function integer(value: unknown, minimum = 0): boolean {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function publicationFacts(value: Record<string, unknown>): PublicationFacts {
  const failure = value.publication_failure === undefined ? null : value.publication_failure;
  const fallback = value.language_fallback_used === undefined ? false : value.language_fallback_used;
  if ((failure !== null && (typeof failure !== "string" || failure.length === 0)) || typeof fallback !== "boolean") {
    throw new Error("publication language facts are invalid");
  }
  return {publication_failure: failure, language_fallback_used: fallback};
}

export function parseProcessResult(output: string): ProcessResult {
  const value = recordValue(JSON.parse(output), "process");
  fields(value, ["schema_version", "run_id", "target", "status", "exit_code", "duration_ms",
    "command", "effective_policy", "lane_sources", "runtime", "failure", "artifacts", "sdk_observations",
    ...(value.presentation === undefined ? [] : ["presentation"]),
    ...["publication_failure", "language_fallback_used"].filter(key => key in value)], "process");
  const publication = publicationFacts(value);
  const presentation = parsePresentation(value.presentation === undefined ? {} : value.presentation);
  if (value.schema_version !== 1 || typeof value.run_id !== "string" || !value.run_id ||
      !["pass", "block", "invalid", "infra_failed"].includes(value.status as string) ||
      !integer(value.duration_ms) || !Array.isArray(value.command) ||
      value.command.some((part) => typeof part !== "string")) {
    throw new Error("process artifact has an unsupported schema or status");
  }
  const target = recordValue(value.target, "process target");
  fields(target, ["repo", "pr", "base", "head"], "process target");
  if (![target.repo, target.base, target.head].every(nullableString) ||
      !(target.pr === null || integer(target.pr, 1))) throw new Error("process target is invalid");
  const policy = recordValue(value.effective_policy, "process policy");
  fields(policy, ["source", "path"], "process policy");
  if (![null, "explicit", "repository", "external", "package"].includes(policy.source as string | null) ||
      !nullableString(policy.path)) throw new Error("process policy is invalid");
  if (Object.values(recordValue(value.lane_sources, "lane sources")).some((count) => !integer(count))) {
    throw new Error("process lane sources are invalid");
  }
  const runtime = recordValue(value.runtime, "process runtime");
  // Watchdog, reasoning-summary, model, and effort settings are additive; legacy envelopes omit them.
  const optionalRuntimeStrings = ["reasoning_summary", "model", "reasoning_effort"];
  fields(runtime, ["replicas", "adjudicate_replicas", "concurrency", "deadline", "discovery_mode",
    "publish", "host_concurrency", "sandbox",
    ...["no_output_seconds", ...optionalRuntimeStrings].filter((key) => key in runtime)], "process runtime");
  if (["replicas", "adjudicate_replicas", "concurrency", "deadline"].some((key) => !integer(runtime[key], 1)) ||
      Number(runtime.deadline) > 1800 || !integer(runtime.host_concurrency) ||
      !["agentic", "inline"].includes(runtime.discovery_mode as string) ||
      !["none", "github-review", "github-comment"].includes(runtime.publish as string) ||
      !["read-only", "danger-full-access"].includes(runtime.sandbox as string) ||
      ("no_output_seconds" in runtime && !integer(runtime.no_output_seconds, 1)) ||
      optionalRuntimeStrings.some((key) =>
        key in runtime && (typeof runtime[key] !== "string" || (runtime[key] as string).length === 0))) {
    throw new Error("process runtime settings are invalid");
  }
  const runtimePolicy: RuntimePolicyFacts = {
    model: "model" in runtime ? (runtime.model as string) : null,
    reasoning_effort: "reasoning_effort" in runtime ? (runtime.reasoning_effort as string) : null,
  };
  artifactManifest(output);
  if (value.sdk_observations !== null) {
    const observed = recordValue(value.sdk_observations, "SDK observations");
    fields(observed, ["exit_code", "signal", "duration_ms", "command"], "SDK observations");
    if (!(observed.exit_code === null || (typeof observed.exit_code === "number" && Number.isSafeInteger(observed.exit_code))) ||
        !(observed.duration_ms === null || integer(observed.duration_ms)) ||
        !nullableString(observed.signal) || !nullableString(observed.command)) throw new Error("SDK observations are invalid");
  }
  const status = value.status as ProcessResult["status"];
  const exitCodes = {pass: 0, block: 1, invalid: 2, infra_failed: 3};
  if (value.exit_code !== exitCodes[status]) throw new Error("process status and exit code disagree");
  let failure: ProcessResult["failure"] = null;
  if (value.failure !== null) {
    const reason = recordValue(value.failure, "process failure");
    fields(reason, ["code", "detail"], "process failure");
    if (typeof reason.code !== "string" || !reason.code || typeof reason.detail !== "string" || !reason.detail) {
      throw new Error("process failure fields must be non-empty strings");
    }
    failure = {code: reason.code, detail: reason.detail};
  }
  if (["invalid", "infra_failed"].includes(status) !== (failure !== null)) {
    throw new Error("process status and failure disagree");
  }
  return {schema_version: 1, run_id: value.run_id, status, exit_code: value.exit_code, failure, presentation,
    runtime: runtimePolicy, ...publication};
}

export function checkConclusionForResult(
  exitCode: number | null,
  output: string,
  checks: CheckPublicationPolicy = {on_block: "failure", on_pass: "success"},
): ReviewResultMapping {
  try {
    const payload = parseProcessResult(output);
    const publication = {publication_failure: payload.publication_failure, language_fallback_used: payload.language_fallback_used,
      runtime: payload.runtime};
    if (exitCode !== null && exitCode !== payload.exit_code) {
      throw new Error(`SDK exit ${exitCode} disagrees with process exit ${payload.exit_code}`);
    }
    if (payload.status === "pass") {
      return {terminalState: "completed", conclusion: checks.on_pass, outcome: "pass", reason: t("process_passed", payload.presentation.locale, {display_name: payload.presentation.display_name}), presentation: payload.presentation, ...publication};
    }
    if (payload.status === "block") {
      return {terminalState: "completed", conclusion: checks.on_block, outcome: "block", reason: t("process_blocked", payload.presentation.locale, {display_name: payload.presentation.display_name}), presentation: payload.presentation, ...publication};
    }
    return {terminalState: "failed", conclusion: "neutral", presentation: payload.presentation, ...publication, reasonCode: payload.failure?.code, reason: payload.failure === null
      ? t("process_status", "en", {display_name: "rvw", status: payload.status}) : `${payload.failure.code}: ${payload.failure.detail}`};
  } catch (error) {
    return {terminalState: "failed", conclusion: "neutral", reasonCode: "process_invalid", reason:
      t("process_invalid", "en", {display_name: "rvw", error: error instanceof Error ? error.message : String(error)})};
  }
}

export const WAVE_KEYS = [
  "discovery_initial", "discovery_retry", "discovery_redispatch",
  "adjudication_initial", "adjudication_initial_retry", "adjudication_expanded", "adjudication_expanded_retry",
] as const;
export type WaveKey = (typeof WAVE_KEYS)[number];
/** Longest runtime wall per executed pipeline wave; null when that wave did not run. */
export type WaveWallSeconds = Record<WaveKey, number | null>;
export interface SummaryFailedLane {
  lane_id: string;
  reason: string;
}

export interface SynthesisFacts {
  status: "ok" | "disabled" | `fallback:${string}`;
  model: string | null;
  reasoning_effort: string | null;
  wall_seconds: number | null;
  tool_calls: number | null;
}

export interface SummaryLanes {
  dispatched: number;
  valid: number;
  /** Lane-hunk receipts: one per (lane, uncovered hunk); rendered as lane_hunk_receipts. */
  uncovered: number;
  /** Distinct changed regions no lane covered; null for legacy summaries. */
  uncovered_regions: number | null;
}

export const REVIEW_EVENTS = ["COMMENT", "REQUEST_CHANGES", "APPROVE"] as const;
export type ReviewEvent = (typeof REVIEW_EVENTS)[number];
export const PUBLISH_ID_LISTS = ["dismissed_review_ids", "dismiss_failed_review_ids"] as const;
export const PUBLISH_THREAD_LISTS = [
  "resolved_thread_ids", "reused_thread_ids", "superseded_thread_ids", "threads_ambiguous",
  "threads_skipped_lane_invalid", "threads_skipped_resolved", "threads_skipped_same_head",
  "threads_skipped_human_reply", "threads_skipped_unverified", "threads_skipped_uncovered",
  "threads_skipped_missing", "threads_skipped_write_failed",
] as const;
/** Python publication facts (summary.publish); carried verbatim into the check text. */
export interface PublishFacts extends Record<(typeof PUBLISH_THREAD_LISTS)[number], string[]>,
  Record<(typeof PUBLISH_ID_LISTS)[number], number[]> {
  channels: PublishChannel[];
  inline_policy: {
    severity_at_least: "suggestion" | "warning" | "blocker";
    max_comments: number | null;
    body_only_count: number;
  };
  event: ReviewEvent | null;
  policy_source: "default" | "repository" | "explicit" | null;
  actor: string | null;
  event_clamped_reason: string | null;
  threads_skipped_reason: string | null;
}

export interface ArtifactSummary extends PublicationFacts {
  schema_version: 1;
  lanes: SummaryLanes;
  failed_lanes: SummaryFailedLane[];
  wave_wall_seconds: WaveWallSeconds | null;
  synthesis: SynthesisFacts;
  findings: Record<"blocker" | "warning" | "suggestion", number>;
  verdicts: Record<"CONFIRMED" | "REJECTED" | "UNCERTAIN", number>;
  blockers: string[];
  markdown: string;
  presentation: PresentationConfig;
  /** Why no review was posted although the run completed; null for legacy summaries. */
  publication_skipped: PublicationSkipped | null;
  /** null for legacy summaries written before publication facts existed. */
  publish: PublishFacts | null;
}

const LEGACY_SYNTHESIS: SynthesisFacts = {
  status: "fallback:not-run", model: null, reasoning_effort: null, wall_seconds: null, tool_calls: null,
};

function synthesisFacts(value: unknown): SynthesisFacts {
  if (value === undefined) return {...LEGACY_SYNTHESIS};
  const record = recordValue(value, "summary synthesis");
  fields(record, ["status", "model", "reasoning_effort", "wall_seconds", "tool_calls"], "summary synthesis");
  const statusValid = typeof record.status === "string" && /^(?:ok|disabled|fallback:[^\s]+)$/.test(record.status);
  const nullableNonempty = (entry: unknown) => entry === null || (typeof entry === "string" && entry.length > 0);
  if (!statusValid || !nullableNonempty(record.model) || !nullableNonempty(record.reasoning_effort) ||
      !(record.wall_seconds === null || (typeof record.wall_seconds === "number" &&
        Number.isFinite(record.wall_seconds) && record.wall_seconds >= 0)) ||
      !(record.tool_calls === null || integer(record.tool_calls))) {
    throw new Error("summary synthesis facts are invalid");
  }
  return record as unknown as SynthesisFacts;
}

function publishFacts(value: unknown): PublishFacts | null {
  if (value === undefined) return null;
  const record = recordValue(value, "summary publish");
  fields(record, ["event", "policy_source", "actor", "event_clamped_reason", "threads_skipped_reason",
    ...PUBLISH_ID_LISTS, ...PUBLISH_THREAD_LISTS,
    ...["channels", "inline_policy"].filter((key) => key in record)], "summary publish");
  if (!(record.event === null || REVIEW_EVENTS.includes(record.event as ReviewEvent)) ||
      !(record.policy_source === null || ["default", "repository", "explicit"].includes(record.policy_source as string)) ||
      ![record.actor, record.event_clamped_reason, record.threads_skipped_reason].every(nullableString)) {
    throw new Error("summary publish facts are invalid");
  }
  for (const key of PUBLISH_ID_LISTS) {
    if (!Array.isArray(record[key]) || (record[key] as unknown[]).some((item) => !integer(item))) {
      throw new Error(`summary publish ${key} must be a list of non-negative integers`);
    }
  }
  for (const key of PUBLISH_THREAD_LISTS) {
    if (!Array.isArray(record[key]) || (record[key] as unknown[]).some((item) => typeof item !== "string" || !item)) {
      throw new Error(`summary publish ${key} must be a list of non-empty strings`);
    }
  }
  const channels = record.channels === undefined ? ["checks", "review"] : record.channels;
  if (!Array.isArray(channels) || channels.length === 0 ||
      channels.some((item) => item !== "checks" && item !== "review")) {
    throw new Error("summary publish channels are invalid");
  }
  const inline = record.inline_policy === undefined
    ? {severity_at_least: "suggestion", max_comments: null, body_only_count: 0}
    : recordValue(record.inline_policy, "summary publish inline_policy");
  fields(inline, ["severity_at_least", "max_comments", "body_only_count"], "summary publish inline_policy");
  if (!["suggestion", "warning", "blocker"].includes(inline.severity_at_least as string) ||
      !(inline.max_comments === null || integer(inline.max_comments)) || !integer(inline.body_only_count)) {
    throw new Error("summary publish inline_policy is invalid");
  }
  return {...record, channels, inline_policy: inline} as unknown as PublishFacts;
}

export type PublicationSkipped = "duplicate_review_same_head" | "on_pass_none" | "head_moved" |
  "review_channel_disabled";

function publicationSkipped(value: unknown): PublicationSkipped | null {
  if (value === undefined || value === null) return null;
  if (!["duplicate_review_same_head", "on_pass_none", "head_moved", "review_channel_disabled"].includes(value as string)) {
    throw new Error("summary publication_skipped is invalid");
  }
  return value as PublicationSkipped;
}

function failedLanes(value: unknown): SummaryFailedLane[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("summary failed_lanes must be a list");
  return value.map((item) => {
    const record = recordValue(item, "summary failed lane");
    fields(record, ["lane_id", "reason"], "summary failed lane");
    if (typeof record.lane_id !== "string" || !record.lane_id || typeof record.reason !== "string" || !record.reason) {
      throw new Error("summary failed lane fields must be non-empty strings");
    }
    return {lane_id: record.lane_id, reason: record.reason};
  });
}

function waveWallSeconds(value: unknown): WaveWallSeconds | null {
  if (value === undefined) return null;
  const record = recordValue(value, "summary wave_wall_seconds");
  fields(record, [...WAVE_KEYS], "summary wave_wall_seconds");
  const result = {} as Record<WaveKey, number | null>;
  for (const key of WAVE_KEYS) {
    const wall = record[key];
    if (!(wall === null || (typeof wall === "number" && Number.isFinite(wall) && wall >= 0))) {
      throw new Error(`summary wave_wall_seconds ${key} must be null or a non-negative number`);
    }
    result[key] = wall;
  }
  return result;
}

/** Consume Python summary facts; no discovery/adjudication recount lives here. */
export function parseArtifactSummary(output: string): ArtifactSummary {
  const value = recordValue(JSON.parse(output), "summary");
  fields(value, ["schema_version", "lanes", "findings", "verdicts", "blockers", "markdown",
    ...(value.presentation === undefined ? [] : ["presentation"]),
    ...["publication_failure", "language_fallback_used", "failed_lanes", "wave_wall_seconds",
      "publication_skipped", "publish", "synthesis"].filter(key => key in value)], "summary");
  const publication = publicationFacts(value);
  const presentation = parsePresentation(value.presentation === undefined ? {} : value.presentation);
  for (const [key, names] of [["findings", ["blocker", "warning", "suggestion"]],
    ["verdicts", ["CONFIRMED", "REJECTED", "UNCERTAIN"]]] as const) {
    const counts = recordValue(value[key], `summary ${key}`);
    fields(counts, [...names], `summary ${key}`);
    if (Object.values(counts).some((count) => !integer(count))) throw new Error(`summary ${key} counts are invalid`);
  }
  if (!Array.isArray(value.blockers) || value.blockers.some((item) => typeof item !== "string")) {
    throw new Error("summary blockers must be strings");
  }
  const lanes = recordValue(value.lanes, "summary lanes");
  fields(lanes, ["dispatched", "valid", "uncovered", ...("uncovered_regions" in lanes ? ["uncovered_regions"] : [])], "summary lanes");
  if (value.schema_version !== 1 || typeof value.markdown !== "string") {
    throw new Error("summary artifact has an unsupported schema");
  }
  for (const field of ["dispatched", "valid", "uncovered"]) {
    if (typeof lanes[field] !== "number" || !Number.isSafeInteger(lanes[field]) || lanes[field] < 0) {
      throw new Error(`summary lanes ${field} must be a non-negative integer`);
    }
  }
  const dispatched = lanes.dispatched as number;
  const valid = lanes.valid as number;
  const uncovered = lanes.uncovered as number;
  const rawRegions = lanes.uncovered_regions;
  if (rawRegions !== undefined && (!integer(rawRegions) || (rawRegions as number) > uncovered)) {
    throw new Error("summary lanes uncovered_regions must be a non-negative integer no greater than the receipt count");
  }
  const uncoveredRegions = rawRegions === undefined ? null : (rawRegions as number);
  if (valid === 0 || valid > dispatched) throw new Error("review coverage has no valid lanes or exceeds dispatched lanes");
  return {schema_version: 1, lanes: {dispatched, valid, uncovered, uncovered_regions: uncoveredRegions},
    markdown: value.markdown, presentation, ...publication,
    failed_lanes: failedLanes(value.failed_lanes), wave_wall_seconds: waveWallSeconds(value.wave_wall_seconds),
    synthesis: synthesisFacts(value.synthesis),
    publication_skipped: publicationSkipped(value.publication_skipped), publish: publishFacts(value.publish),
    findings: value.findings as ArtifactSummary["findings"],
    verdicts: value.verdicts as ArtifactSummary["verdicts"], blockers: value.blockers as string[]};
}
