import {describe, expect, it} from "vitest";

import {
  ConfigMissingError,
  configErrorResponse,
  requiredConfig,
} from "./config";

describe("required deployer configuration", () => {
  it.each([undefined, "", "   "])("rejects missing proxy host %#", (value) => {
    expect(() =>
      requiredConfig({CODEX_PROXY_HOST: value, GITHUB_APP_ID: "123"}),
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
      requiredConfig({CODEX_PROXY_HOST: "proxy.example", GITHUB_APP_ID: value}),
    ).toThrowError(
      expect.objectContaining({
        code: "config_missing",
        variable: "GITHUB_APP_ID",
        message: "config_missing: GITHUB_APP_ID",
      }),
    );
  });

  it("returns one trimmed immutable snapshot", () => {
    expect(
      requiredConfig({CODEX_PROXY_HOST: " proxy.example ", GITHUB_APP_ID: " 123 "}),
    ).toEqual({codexProxyHost: "proxy.example", githubAppId: "123"});
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
