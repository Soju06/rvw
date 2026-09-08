import {t} from "./i18n";
import {parsePresentation, type PresentationConfig} from "./presentation";
import {artifactManifest} from "./artifacts";

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

export interface ReviewResultMapping extends Partial<PublicationFacts> {
  terminalState: "completed" | "failed";
  conclusion: CheckConclusion;
  reason: string;
  reasonCode?: string;
  presentation?: PresentationConfig;
}

export interface ProcessResult extends PublicationFacts {
  schema_version: 1;
  run_id: string;
  status: "pass" | "block" | "invalid" | "infra_failed";
  exit_code: number;
  failure: {code: string; detail: string} | null;
  presentation: PresentationConfig;
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
  fields(runtime, ["replicas", "adjudicate_replicas", "concurrency", "deadline", "discovery_mode",
    "publish", "host_concurrency", "sandbox"], "process runtime");
  if (["replicas", "adjudicate_replicas", "concurrency", "deadline"].some((key) => !integer(runtime[key], 1)) ||
      Number(runtime.deadline) > 1800 || !integer(runtime.host_concurrency) ||
      !["agentic", "inline"].includes(runtime.discovery_mode as string) ||
      !["none", "github-comment"].includes(runtime.publish as string) ||
      !["read-only", "danger-full-access"].includes(runtime.sandbox as string)) {
    throw new Error("process runtime settings are invalid");
  }
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
  return {schema_version: 1, run_id: value.run_id, status, exit_code: value.exit_code, failure, presentation, ...publication};
}

export function checkConclusionForResult(
  exitCode: number | null,
  output: string,
): ReviewResultMapping {
  try {
    const payload = parseProcessResult(output);
    const publication = {publication_failure: payload.publication_failure, language_fallback_used: payload.language_fallback_used};
    if (exitCode !== null && exitCode !== payload.exit_code) {
      throw new Error(`SDK exit ${exitCode} disagrees with process exit ${payload.exit_code}`);
    }
    if (payload.status === "pass") {
      return {terminalState: "completed", conclusion: "success", reason: t("process_passed", payload.presentation.locale, {display_name: payload.presentation.display_name}), presentation: payload.presentation, ...publication};
    }
    if (payload.status === "block") {
      return {terminalState: "completed", conclusion: "failure", reason: t("process_blocked", payload.presentation.locale, {display_name: payload.presentation.display_name}), presentation: payload.presentation, ...publication};
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

export interface SummaryLanes {
  dispatched: number;
  valid: number;
  /** Lane-hunk receipts: one per (lane, uncovered hunk); rendered as lane_hunk_receipts. */
  uncovered: number;
  /** Distinct changed regions no lane covered; null for legacy summaries. */
  uncovered_regions: number | null;
}

export interface ArtifactSummary extends PublicationFacts {
  schema_version: 1;
  lanes: SummaryLanes;
  failed_lanes: SummaryFailedLane[];
  wave_wall_seconds: WaveWallSeconds | null;
  findings: Record<"blocker" | "warning" | "suggestion", number>;
  verdicts: Record<"CONFIRMED" | "REJECTED" | "UNCERTAIN", number>;
  blockers: string[];
  markdown: string;
  presentation: PresentationConfig;
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
    ...["publication_failure", "language_fallback_used", "failed_lanes", "wave_wall_seconds"].filter(key => key in value)], "summary");
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
    findings: value.findings as ArtifactSummary["findings"],
    verdicts: value.verdicts as ArtifactSummary["verdicts"], blockers: value.blockers as string[]};
}
