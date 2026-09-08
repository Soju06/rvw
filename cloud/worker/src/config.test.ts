import {describe, expect, it} from "vitest";

import {
  ConfigIncoherentError,
  ConfigInvalidError,
  ConfigMissingError,
  configErrorResponse,
  isConfigError,
  jobDeadlineCoversReviewBudget,
  jobDeadlineMinutes,
  minimumJobDeadlineMinutes,
  requiredConfig,
  reviewDeadlineSeconds,
} from "./config";

const DEADLINES = {RVW_REVIEW_DEADLINE_SECONDS: "900", RVW_JOB_DEADLINE_MINUTES: "120"};

describe("required deployer configuration", () => {
  it.each([undefined, "", "   "])("rejects missing proxy host %#", (value) => {
    expect(() =>
      requiredConfig({CODEX_PROXY_HOST: value, GITHUB_APP_ID: "123", ...DEADLINES}),
    ).toThrowError(
      expect.objectContaining({
        code: "config_missing",
        variable: "CODEX_PROXY_HOST",
        message: "config_missing: CODEX_PROXY_HOST",
      }),
    );
  });

  it.each([undefined, "", "\t"])("rejects missing App ID %#", (value) => {
    expect(() =>
      requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: value, ...DEADLINES}),
    ).toThrowError(
      expect.objectContaining({
        code: "config_missing",
        variable: "GITHUB_APP_ID",
        message: "config_missing: GITHUB_APP_ID",
      }),
    );
  });

  it("returns one trimmed immutable snapshot", () => {
    const config = requiredConfig({CODEX_PROXY_HOST: " proxy.example ", GITHUB_APP_ID: " 123 ", ...DEADLINES});
    expect(config).toEqual({codexProxyHost: "proxy.example", githubAppId: "123",
      reviewDeadlineSeconds: 900, jobDeadlineMinutes: 120});
    expect(Object.isFrozen(config)).toBe(true);
  });

  it.each([undefined, "", " "])("fails closed when the review deadline var is missing %#", (value) => {
    expect(() => requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
      RVW_REVIEW_DEADLINE_SECONDS: value, RVW_JOB_DEADLINE_MINUTES: "120"})).toThrowError(
      expect.objectContaining({code: "config_missing", variable: "RVW_REVIEW_DEADLINE_SECONDS"}));
  });

  it.each(["abc", "0", "-5", "1801", "900.5", "9e2"])("rejects review deadline %s", (value) => {
    expect(() => reviewDeadlineSeconds(value)).toThrow(ConfigInvalidError);
    expect(() => requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
      RVW_REVIEW_DEADLINE_SECONDS: value, RVW_JOB_DEADLINE_MINUTES: "600"})).toThrowError(
      expect.objectContaining({code: "config_invalid", variable: "RVW_REVIEW_DEADLINE_SECONDS"}));
  });

  it("accepts the CLI ceiling and the smallest positive deadline", () => {
    expect(reviewDeadlineSeconds("1800")).toBe(1800);
    expect(reviewDeadlineSeconds(" 1 ")).toBe(1);
  });
});

describe("job deadline covers the review budget", () => {
  it("requires job minutes * 60 >= 5 * review seconds + 600", () => {
    expect(minimumJobDeadlineMinutes(900)).toBe(85);
    expect(minimumJobDeadlineMinutes(600)).toBe(60);
    expect(minimumJobDeadlineMinutes(1500)).toBe(135);
    expect(jobDeadlineCoversReviewBudget(85, 900)).toBe(true);
    expect(jobDeadlineCoversReviewBudget(84, 900)).toBe(false);
    expect(jobDeadlineCoversReviewBudget(90, 900)).toBe(true);
    expect(jobDeadlineCoversReviewBudget(90, 1500)).toBe(false);
    expect(jobDeadlineCoversReviewBudget(120, 900)).toBe(true);
  });

  it.each([["120", "900"], ["85", "900"], ["90", "900"], ["135", "1500"], ["60", "600"]])(
    "accepts %s minutes for %s seconds", (minutes, seconds) => {
      expect(requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
        RVW_JOB_DEADLINE_MINUTES: minutes, RVW_REVIEW_DEADLINE_SECONDS: seconds})).toMatchObject({
        reviewDeadlineSeconds: Number(seconds), jobDeadlineMinutes: Number(minutes)});
    },
  );

  it.each([["84", "900", 85], ["90", "1500", 135], ["30", "600", 60]])(
    "fails closed with a machine-readable reason for %s minutes and %s seconds", (minutes, seconds, minimum) => {
      let caught: unknown;
      try {
        requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
          RVW_JOB_DEADLINE_MINUTES: minutes, RVW_REVIEW_DEADLINE_SECONDS: seconds});
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(ConfigIncoherentError);
      expect(isConfigError(caught)).toBe(true);
      expect(caught).toMatchObject({code: "config_incoherent", reason: "job_deadline_below_review_budget",
        jobDeadlineMinutes: Number(minutes), reviewDeadlineSeconds: Number(seconds), minimumJobDeadlineMinutes: minimum});
    },
  );

  it("defaults an absent job cap to 90 minutes and still checks coherence", () => {
    expect(jobDeadlineMinutes(undefined)).toBe(90);
    expect(requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
      RVW_REVIEW_DEADLINE_SECONDS: "900"}).jobDeadlineMinutes).toBe(90);
    expect(() => requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
      RVW_REVIEW_DEADLINE_SECONDS: "1200"})).toThrow(ConfigIncoherentError);
  });

  it.each(["soon", "", "0", "-3", "90.5", "1e2"])("fails closed on malformed job cap %s", (value) => {
    expect(() => jobDeadlineMinutes(value)).toThrow(ConfigInvalidError);
    expect(() => requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: "1",
      RVW_JOB_DEADLINE_MINUTES: value, RVW_REVIEW_DEADLINE_SECONDS: "900"})).toThrowError(
      expect.objectContaining({code: "config_invalid", variable: "RVW_JOB_DEADLINE_MINUTES"}));
  });

  it("accepts a trimmed positive job cap", () => {
    expect(jobDeadlineMinutes(" 120 ")).toBe(120);
  });

  it("serializes the incoherence as a structured service error", async () => {
    const response = configErrorResponse(new ConfigIncoherentError(84, 900, 85));
    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: "config_incoherent", reason: "job_deadline_below_review_budget",
      job_deadline_minutes: 84, review_deadline_seconds: 900, minimum_job_deadline_minutes: 85,
      message: expect.stringContaining("config_incoherent: job_deadline_below_review_budget"),
    });
  });

  it("serializes a clear structured service error", async () => {
    const response = configErrorResponse(new ConfigMissingError("CODEX_PROXY_HOST"));
    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: "config_missing",
      variable: "CODEX_PROXY_HOST",
      message: "config_missing: CODEX_PROXY_HOST",
    });
  });
});
