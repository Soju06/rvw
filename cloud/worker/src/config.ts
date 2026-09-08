import {MAX_REVIEW_DEADLINE_SECONDS} from "./sandbox-auth";

export type RequiredVariable =
  | "CODEX_PROXY_HOST"
  | "GITHUB_APP_ID"
  | "RVW_REVIEW_DEADLINE_SECONDS"
  | "RVW_JOB_DEADLINE_MINUTES";

/** Job cap used when `RVW_JOB_DEADLINE_MINUTES` is absent; a present but malformed value fails closed. */
export const DEFAULT_JOB_DEADLINE_MINUTES = 90;

export {MAX_REVIEW_DEADLINE_SECONDS};
/** Runtime waves on the no-adjudication-retry path with the dead-lane skip: discovery initial + retry, adjudication initial, expanded (2D). */
export const REVIEW_BUDGET_WAVES = 5;
/** Provisioning, clone, publish, and artifact upload slack in seconds. */
export const JOB_SLACK_SECONDS = 600;

export interface ConfigEnvironment {
  CODEX_PROXY_HOST?: string;
  GITHUB_APP_ID?: string;
  RVW_REVIEW_DEADLINE_SECONDS?: string;
  RVW_JOB_DEADLINE_MINUTES?: string;
}

export interface RequiredConfig {
  codexProxyHost: string;
  githubAppId: string;
  /** Explicit `--deadline` passed to `rvw run`, in seconds. */
  reviewDeadlineSeconds: number;
  /** Hard job cap enforced by the Durable Object alarm, in minutes. */
  jobDeadlineMinutes: number;
}

export class ConfigMissingError extends Error {
  readonly code = "config_missing";

  constructor(readonly variable: RequiredVariable) {
    super(`config_missing: ${variable}`);
    this.name = "ConfigMissingError";
  }
}

export class ConfigInvalidError extends Error {
  readonly code = "config_invalid";

  constructor(readonly variable: RequiredVariable, readonly detail: string) {
    super(`config_invalid: ${variable} ${detail}`);
    this.name = "ConfigInvalidError";
  }
}

export class ConfigIncoherentError extends Error {
  readonly code = "config_incoherent";
  readonly reason = "job_deadline_below_review_budget";

  constructor(
    readonly jobDeadlineMinutes: number,
    readonly reviewDeadlineSeconds: number,
    readonly minimumJobDeadlineMinutes: number,
  ) {
    super(
      `config_incoherent: job_deadline_below_review_budget RVW_JOB_DEADLINE_MINUTES=${jobDeadlineMinutes} ` +
        `is below the ${minimumJobDeadlineMinutes} minutes required by RVW_REVIEW_DEADLINE_SECONDS=${reviewDeadlineSeconds}`,
    );
    this.name = "ConfigIncoherentError";
  }
}

export type ConfigError = ConfigMissingError | ConfigInvalidError | ConfigIncoherentError;

export function isConfigError(error: unknown): error is ConfigError {
  return error instanceof ConfigMissingError || error instanceof ConfigInvalidError ||
    error instanceof ConfigIncoherentError;
}

function requiredValue(value: string | undefined, variable: RequiredVariable): string {
  const trimmed = value?.trim() ?? "";
  if (trimmed.length === 0) throw new ConfigMissingError(variable);
  return trimmed;
}

/** Parse the explicit review deadline; missing or out-of-range values fail closed. */
export function reviewDeadlineSeconds(raw: string | undefined): number {
  const trimmed = requiredValue(raw, "RVW_REVIEW_DEADLINE_SECONDS");
  if (!/^\d+$/.test(trimmed)) {
    throw new ConfigInvalidError("RVW_REVIEW_DEADLINE_SECONDS", "must be a whole number of seconds");
  }
  const value = Number.parseInt(trimmed, 10);
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_REVIEW_DEADLINE_SECONDS) {
    throw new ConfigInvalidError("RVW_REVIEW_DEADLINE_SECONDS", `must be between 1 and ${MAX_REVIEW_DEADLINE_SECONDS}`);
  }
  return value;
}

/** Parse the hard job cap; absent means the historical 90-minute default, malformed fails closed. */
export function jobDeadlineMinutes(raw: string | undefined): number {
  if (raw === undefined) return DEFAULT_JOB_DEADLINE_MINUTES;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    throw new ConfigInvalidError("RVW_JOB_DEADLINE_MINUTES", "must be a positive whole number of minutes");
  }
  const value = Number.parseInt(trimmed, 10);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new ConfigInvalidError("RVW_JOB_DEADLINE_MINUTES", "must be a positive whole number of minutes");
  }
  return value;
}

/** Smallest job cap (whole minutes) that covers `REVIEW_BUDGET_WAVES * D + JOB_SLACK_SECONDS`. */
export function minimumJobDeadlineMinutes(reviewDeadline: number): number {
  return Math.ceil((REVIEW_BUDGET_WAVES * reviewDeadline + JOB_SLACK_SECONDS) / 60);
}

export function jobDeadlineCoversReviewBudget(jobMinutes: number, reviewDeadline: number): boolean {
  return jobMinutes * 60 >= REVIEW_BUDGET_WAVES * reviewDeadline + JOB_SLACK_SECONDS;
}

export function requiredConfig(env: ConfigEnvironment): RequiredConfig {
  const codexProxyHost = requiredValue(env.CODEX_PROXY_HOST, "CODEX_PROXY_HOST");
  const githubAppId = requiredValue(env.GITHUB_APP_ID, "GITHUB_APP_ID");
  const reviewDeadline = reviewDeadlineSeconds(env.RVW_REVIEW_DEADLINE_SECONDS);
  const jobMinutes = jobDeadlineMinutes(env.RVW_JOB_DEADLINE_MINUTES);
  if (!jobDeadlineCoversReviewBudget(jobMinutes, reviewDeadline)) {
    throw new ConfigIncoherentError(jobMinutes, reviewDeadline, minimumJobDeadlineMinutes(reviewDeadline));
  }
  return Object.freeze({
    codexProxyHost,
    githubAppId,
    reviewDeadlineSeconds: reviewDeadline,
    jobDeadlineMinutes: jobMinutes,
  });
}

export function configErrorResponse(error: ConfigError): Response {
  const body = error instanceof ConfigIncoherentError
    ? {error: error.code, reason: error.reason, job_deadline_minutes: error.jobDeadlineMinutes,
      review_deadline_seconds: error.reviewDeadlineSeconds,
      minimum_job_deadline_minutes: error.minimumJobDeadlineMinutes, message: error.message}
    : {error: error.code, variable: error.variable, message: error.message};
  return Response.json(body, {status: 500});
}
