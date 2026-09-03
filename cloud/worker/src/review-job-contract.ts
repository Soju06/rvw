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

interface AutoPayload {
  verdict: "PASS" | "BLOCK";
  run_id: string;
}

function parseAutoPayload(output: string): AutoPayload | null {
  try {
    const value: unknown = JSON.parse(output);
    if (typeof value !== "object" || value === null) return null;
    const record = value as Record<string, unknown>;
    if (
      (record.verdict !== "PASS" && record.verdict !== "BLOCK") ||
      typeof record.run_id !== "string" ||
      record.run_id.length === 0
    ) {
      return null;
    }
    return {verdict: record.verdict, run_id: record.run_id};
  } catch {
    return null;
  }
}

export function checkConclusionForResult(
  exitCode: number | null,
  output: string,
): ReviewResultMapping {
  const payload = parseAutoPayload(output);
  if (exitCode === 0 && payload?.verdict === "PASS") {
    return {
      terminalState: "completed",
      conclusion: "success",
      reason: "rvw auto passed",
    };
  }
  if (exitCode === 1 && payload?.verdict === "BLOCK") {
    return {
      terminalState: "completed",
      conclusion: "failure",
      reason: "rvw auto found a blocking result",
    };
  }
  return {
    terminalState: "failed",
    conclusion: "neutral",
    reason: payload
      ? `rvw auto exit ${exitCode === null ? "unknown" : exitCode} did not match ${payload.verdict}`
      : "rvw auto result was missing or unparseable",
  };
}

export interface ArtifactSummary {
  lanesDispatched: number;
  lanesValid: number;
  uncovered: number;
  findings: number;
  findingsBySeverity: Record<string, number>;
  verdicts: Record<string, number>;
}

function recordValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} artifact must be an object`);
  }
  return value as Record<string, unknown>;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} artifact field must be a non-negative integer`);
  }
  return value;
}

export function summarizeArtifacts(discoverJson: string, outcomeJson: string): ArtifactSummary {
  let discoverValue: unknown;
  let outcomeValue: unknown;
  try {
    discoverValue = JSON.parse(discoverJson);
    outcomeValue = JSON.parse(outcomeJson);
  } catch (error) {
    throw new Error("review artifact JSON is unparseable", {cause: error});
  }
  const discover = recordValue(discoverValue, "discover");
  const outcome = recordValue(outcomeValue, "outcome");
  if (!Array.isArray(discover.coverage) || !Array.isArray(discover.findings)) {
    throw new Error("discover artifact must contain coverage and findings arrays");
  }
  const verdictMap = recordValue(outcome.verdicts, "outcome verdicts");

  let lanesDispatched = 0;
  let lanesValid = 0;
  let coverageFindings = 0;
  let uncovered = 0;
  for (const itemValue of discover.coverage) {
    const item = recordValue(itemValue, "coverage");
    lanesDispatched += nonNegativeInteger(item.dispatched, "coverage dispatched");
    lanesValid += nonNegativeInteger(item.valid, "coverage valid");
    coverageFindings += nonNegativeInteger(item.findings, "coverage findings");
    if (!Array.isArray(item.uncovered)) {
      throw new Error("coverage artifact uncovered field must be an array");
    }
    uncovered += item.uncovered.length;
  }

  const findingsBySeverity: Record<string, number> = {};
  for (const findingValue of discover.findings) {
    const finding = recordValue(findingValue, "finding");
    if (typeof finding.severity !== "string" || finding.severity.length === 0) {
      throw new Error("finding artifact severity must be a string");
    }
    findingsBySeverity[finding.severity] = (findingsBySeverity[finding.severity] ?? 0) + 1;
  }

  const verdicts: Record<string, number> = {};
  for (const verdict of Object.values(verdictMap)) {
    if (typeof verdict !== "string" || verdict.length === 0) {
      throw new Error("outcome artifact verdict must be a string");
    }
    verdicts[verdict] = (verdicts[verdict] ?? 0) + 1;
  }

  return {
    lanesDispatched,
    lanesValid,
    uncovered,
    findings: Math.max(discover.findings.length, coverageFindings),
    findingsBySeverity,
    verdicts,
  };
}
