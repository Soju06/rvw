import {describe, expect, it} from "vitest";

import {
  buildSandboxProcessEnv,
  validateTargetInput,
} from "./spike-contract";

describe("validateTargetInput", () => {
  it.each([
    ["https://github.com/Soju06/rvw", "2968629"],
    ["https://github.com/cloudflare/sandbox-sdk.git", "0123456789abcdef0123456789abcdef01234567"],
  ])("accepts a safe HTTPS repository URL and short or full SHA", (repoUrl, targetSha) => {
    expect(validateTargetInput(repoUrl, targetSha)).toEqual({repoUrl, targetSha});
  });

  it.each([
    [null, "2968629"],
    ["https://github.com/Soju06/rvw", null],
    ["http://github.com/Soju06/rvw", "2968629"],
    ["https://git.example.test/team/project", "2968629"],
    ["https://user:secret@github.com/Soju06/rvw", "2968629"],
    ["https://github.com/Soju06/rvw?ref=main", "2968629"],
    ["https://github.com/Soju06/rvw/extra", "2968629"],
    ["https://github.com/Soju06/rvw';touch /tmp/pwned;'", "2968629"],
    ["https://github.com/Soju06/rvw", "abcdef"],
    ["https://github.com/Soju06/rvw", "ABCDEF1"],
    ["https://github.com/Soju06/rvw", "g123456"],
  ])("rejects unsafe or malformed input", (repoUrl, targetSha) => {
    expect(validateTargetInput(repoUrl, targetSha)).toBeNull();
  });
});

describe("buildSandboxProcessEnv", () => {
  it("passes only the placeholder credential and proxy URL", () => {
    const processEnv = buildSandboxProcessEnv("proxy.example");

    expect(processEnv).toEqual({
      CODEX_API_KEY: "placeholder-not-a-secret",
      CODEX_BASE_URL: "https://proxy.example/backend-api/codex",
    });
    expect(Object.keys(processEnv)).toHaveLength(2);
  });
});

import {REASONING_EFFORT_VALUES} from "./sandbox-auth";
import {SPIKE_REASONING_EFFORT_VALUES, parseStartOverrides} from "./spike-contract";

describe("parseStartOverrides", () => {
  it("keeps the import-free effort list identical to the shared enum", () => {
    expect([...SPIKE_REASONING_EFFORT_VALUES]).toEqual([...REASONING_EFFORT_VALUES]);
  });

  it.each([undefined])("selects no override for an absent body %#", (body) => {
    expect(parseStartOverrides(body)).toEqual({overrides: {}});
  });

  it("accepts an empty object and each key on its own", () => {
    expect(parseStartOverrides({})).toEqual({overrides: {}});
    expect(parseStartOverrides({model: "gpt-6-astra"})).toEqual({overrides: {model: "gpt-6-astra"}});
    expect(parseStartOverrides({reasoning_effort: "high"})).toEqual({overrides: {reasoning_effort: "high"}});
    expect(parseStartOverrides({model: "gpt-6-astra", reasoning_effort: "high"}))
      .toEqual({overrides: {model: "gpt-6-astra", reasoning_effort: "high"}});
  });

  it("trims the model", () => {
    expect(parseStartOverrides({model: "  gpt-6-astra "})).toEqual({overrides: {model: "gpt-6-astra"}});
  });

  it.each(["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"])(
    "accepts the named effort %s", (effort) => {
      expect(parseStartOverrides({reasoning_effort: effort})).toEqual({overrides: {reasoning_effort: effort}});
    },
  );

  it.each([
    ["a string", "gpt-6-astra", /JSON object/],
    ["a number", 3, /JSON object/],
    ["an array", [{model: "gpt-6-astra"}], /JSON object/],
    ["a JSON null", null, /JSON object/],
    ["an unknown key", {model: "gpt-6-astra", modle: "typo"}, /unsupported keys: modle/],
    ["a camelCase effort key", {reasoningEffort: "high"}, /unsupported keys: reasoningEffort/],
    ["an empty model", {model: ""}, /model must be a non-empty string/],
    ["a whitespace model", {model: "   "}, /model must be a non-empty string/],
    ["a non-string model", {model: 5}, /model must be a non-empty string/],
    ["a null model", {model: null}, /model must be a non-empty string/],
    ["an off-enum effort", {reasoning_effort: "turbo"}, /reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max, ultra, persistent/],
    ["an upper-case effort", {reasoning_effort: "Max"}, /reasoning_effort must be one of/],
    ["an untrimmed effort", {reasoning_effort: " high"}, /reasoning_effort must be one of/],
    ["a non-string effort", {reasoning_effort: 1}, /reasoning_effort must be one of/],
    ["a null effort", {reasoning_effort: null}, /reasoning_effort must be one of/],
  ])("rejects %s", (_label, body, pattern) => {
    const parsed = parseStartOverrides(body);
    expect(parsed).toHaveProperty("error");
    expect((parsed as {error: string}).error).toMatch(pattern);
  });
});
