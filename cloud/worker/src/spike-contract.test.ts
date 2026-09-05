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
