const TARGET_SHA_PATTERN = /^[0-9a-f]{7,40}$/;
const GITHUB_REPOSITORY_URL_PATTERN =
  /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*(?:\.git)?$/;

export interface SpikeTarget {
  repoUrl: string;
  targetSha: string;
}

export function validateTargetInput(
  repoUrl: string | null,
  targetSha: string | null,
): SpikeTarget | null {
  if (
    !repoUrl ||
    !targetSha ||
    !GITHUB_REPOSITORY_URL_PATTERN.test(repoUrl) ||
    !TARGET_SHA_PATTERN.test(targetSha)
  ) {
    return null;
  }
  return {repoUrl, targetSha};
}

export function buildSandboxProcessEnv(
  proxyHost: string,
): Record<"CODEX_API_KEY" | "CODEX_BASE_URL", string> {
  return {
    CODEX_API_KEY: "placeholder-not-a-secret",
    CODEX_BASE_URL: `https://${proxyHost}/backend-api/codex`,
  };
}

// Mirrors REASONING_EFFORT_VALUES in sandbox-auth.ts; this module stays import-free and a
// vitest asserts the two lists agree so a drift cannot admit an effort the CLI rejects.
const START_REASONING_EFFORT_VALUES = [
  "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent",
] as const;
export const SPIKE_REASONING_EFFORT_VALUES: readonly string[] = START_REASONING_EFFORT_VALUES;
const START_REASONING_EFFORTS: ReadonlySet<string> = new Set<string>(START_REASONING_EFFORT_VALUES);
const START_OVERRIDE_KEYS = ["model", "reasoning_effort"] as const;

/** Per-request Codex runtime overrides carried by the optional `/start` JSON body. */
export interface StartOverrides {
  model?: string;
  reasoning_effort?: (typeof START_REASONING_EFFORT_VALUES)[number];
}

/**
 * Parse the optional `/start` body. An absent body (undefined) selects no override; a JSON
 * `null`, array, or scalar is a non-object and fails closed, as do unknown keys, so a typo
 * cannot silently run the default experiment cell.
 */
export function parseStartOverrides(body: unknown): {overrides: StartOverrides} | {error: string} {
  if (body === undefined) return {overrides: {}};
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return {error: "start body must be a JSON object with optional model and reasoning_effort"};
  }
  const record = body as Record<string, unknown>;
  const unknown = Object.keys(record).filter((key) => !(START_OVERRIDE_KEYS as readonly string[]).includes(key));
  if (unknown.length > 0) {
    return {error: `start body has unsupported keys: ${unknown.sort().join(", ")}; allowed keys are model and reasoning_effort`};
  }
  const overrides: StartOverrides = {};
  if ("model" in record) {
    const model = typeof record.model === "string" ? record.model.trim() : "";
    if (model.length === 0) return {error: "model must be a non-empty string"};
    overrides.model = model;
  }
  if ("reasoning_effort" in record) {
    const effort = record.reasoning_effort;
    if (typeof effort !== "string" || !START_REASONING_EFFORTS.has(effort)) {
      return {error: `reasoning_effort must be one of: ${START_REASONING_EFFORT_VALUES.join(", ")}`};
    }
    overrides.reasoning_effort = effort as StartOverrides["reasoning_effort"];
  }
  return {overrides};
}
