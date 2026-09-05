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

export function deadlineMinutes(raw: string | undefined): number {
  if (raw === undefined || !/^\d+$/.test(raw)) return 90;
  const value = Number.parseInt(raw, 10);
  return Number.isSafeInteger(value) && value > 0 ? value : 90;
}

export function isDeadlineReached(nowMs: number, deadlineMs: number): boolean {
  return nowMs >= deadlineMs;
}

export interface ReviewResultMapping {
  terminalState: "completed" | "failed";
  conclusion: CheckConclusion;
  reason: string;
}

export interface ProcessResult {
  schema_version: 1;
  run_id: string;
  status: "pass" | "block" | "invalid" | "infra_failed";
  exit_code: number;
  failure: {code: string; detail: string} | null;
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

export function parseProcessResult(output: string): ProcessResult {
  const value = recordValue(JSON.parse(output), "process");
  fields(value, ["schema_version", "run_id", "target", "status", "exit_code", "duration_ms",
    "command", "effective_policy", "lane_sources", "runtime", "failure", "artifacts", "sdk_observations"], "process");
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
  return {schema_version: 1, run_id: value.run_id, status, exit_code: value.exit_code, failure};
}

export function checkConclusionForResult(
  exitCode: number | null,
  output: string,
): ReviewResultMapping {
  try {
    const payload = parseProcessResult(output);
    if (exitCode !== null && exitCode !== payload.exit_code) {
      throw new Error(`SDK exit ${exitCode} disagrees with process exit ${payload.exit_code}`);
    }
    if (payload.status === "pass") {
      return {terminalState: "completed", conclusion: "success", reason: "rvw run passed"};
    }
    if (payload.status === "block") {
      return {terminalState: "completed", conclusion: "failure", reason: "rvw run found a blocking result"};
    }
    return {terminalState: "failed", conclusion: "neutral", reason: payload.failure === null
      ? `rvw run ${payload.status}` : `${payload.failure.code}: ${payload.failure.detail}`};
  } catch (error) {
    return {terminalState: "failed", conclusion: "neutral", reason:
      `rvw process result was missing or invalid: ${error instanceof Error ? error.message : String(error)}`};
  }
}

export interface ArtifactSummary {
  schema_version: 1;
  lanes: {dispatched: number; valid: number; uncovered: number};
  markdown: string;
}

/** Consume Python summary facts; no discovery/adjudication recount lives here. */
export function parseArtifactSummary(output: string): ArtifactSummary {
  const value = recordValue(JSON.parse(output), "summary");
  fields(value, ["schema_version", "lanes", "findings", "verdicts", "blockers", "markdown"], "summary");
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
  fields(lanes, ["dispatched", "valid", "uncovered"], "summary lanes");
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
  if (valid === 0 || valid > dispatched) throw new Error("review coverage has no valid lanes or exceeds dispatched lanes");
  return {schema_version: 1, lanes: {dispatched, valid, uncovered}, markdown: value.markdown};
}
