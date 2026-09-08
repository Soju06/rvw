import {describe, expect, it, vi} from "vitest";

import {ConfigMissingError, requiredConfig} from "./config";
import {
  codexOutboundHandler,
  configureCodexEgress,
  REVIEW_EGRESS_HOSTS,
  reviewEgressAllowlist,
  type OutboundConfigurable,
} from "./sandbox-config";

function fakeSandbox() {
  return {
    setOutboundByHosts: vi.fn().mockResolvedValue(undefined),
    setAllowedHosts: vi.fn().mockResolvedValue(undefined),
  };
}

describe("runtime Codex egress registration", () => {
  it("registers distinct deployer hosts on distinct sandboxes", async () => {
    const first = fakeSandbox();
    const second = fakeSandbox();
    await configureCodexEgress(first as OutboundConfigurable, "proxy-one.example");
    await configureCodexEgress(second as OutboundConfigurable, "proxy-two.example");
    expect(first.setOutboundByHosts).toHaveBeenCalledWith({"proxy-one.example": "codex"});
    expect(second.setOutboundByHosts).toHaveBeenCalledWith({"proxy-two.example": "codex"});
    expect(first.setOutboundByHosts).not.toHaveBeenCalledWith({"proxy-two.example": "codex"});
  });

  it("allowlists only the proxy host and the two GitHub hosts for the whole run", async () => {
    const withToken = fakeSandbox();
    await configureCodexEgress(withToken as OutboundConfigurable, "proxy-one.example", "ghs_scoped");
    expect(withToken.setAllowedHosts).toHaveBeenCalledTimes(1);
    expect(withToken.setAllowedHosts).toHaveBeenCalledWith(["proxy-one.example", "api.github.com", "github.com"]);
    expect(withToken.setOutboundByHosts.mock.invocationCallOrder[0]).toBeLessThan(
      withToken.setAllowedHosts.mock.invocationCallOrder[0],
    );

    const withoutToken = fakeSandbox();
    await configureCodexEgress(withoutToken as OutboundConfigurable, "proxy-two.example");
    expect(withoutToken.setAllowedHosts).toHaveBeenCalledWith(["proxy-two.example", "api.github.com", "github.com"]);
    expect(reviewEgressAllowlist("proxy-three.example")).toEqual(["proxy-three.example", ...REVIEW_EGRESS_HOSTS]);
    expect(JSON.stringify(withToken.setAllowedHosts.mock.calls)).not.toContain("ghs_scoped");
  });

  it("registers no host when required configuration is absent", async () => {
    const sandbox = fakeSandbox();
    expect(() => requiredConfig({GITHUB_APP_ID: "123"})).toThrow(ConfigMissingError);
    expect(sandbox.setOutboundByHosts).not.toHaveBeenCalled();
    expect(sandbox.setAllowedHosts).not.toHaveBeenCalled();
  });

  it("injects only for the currently configured hostname", async () => {
    const fetcher = vi.fn(async (request: Request) => {
      return Response.json({authorization: request.headers.get("Authorization")});
    });
    for (const hostname of ["proxy-one.example", "proxy-two.example"]) {
      const response = await codexOutboundHandler(
        new Request(`https://${hostname}/backend-api/codex`),
        {CODEX_PROXY_HOST: hostname, GITHUB_APP_ID: "123", RVW_REVIEW_DEADLINE_SECONDS: "900", CODEX_API_KEY: "secret"},
        fetcher,
      );
      await expect(response.json()).resolves.toEqual({authorization: "Bearer secret"});
    }
    await expect(
      codexOutboundHandler(
        new Request("https://stale.example/backend-api/codex"),
        {CODEX_PROXY_HOST: "proxy-two.example", GITHUB_APP_ID: "123", RVW_REVIEW_DEADLINE_SECONDS: "900", CODEX_API_KEY: "secret"},
        fetcher,
      ),
    ).rejects.toThrow("outbound host does not match CODEX_PROXY_HOST");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("an unconfigured proxy handler injects nothing", async () => {
    const fetcher = vi.fn();
    await expect(
      codexOutboundHandler(
        new Request("https://stale.example/backend-api/codex"),
        {CODEX_PROXY_HOST: "", GITHUB_APP_ID: "123", RVW_REVIEW_DEADLINE_SECONDS: "900", CODEX_API_KEY: "secret"},
        fetcher,
      ),
    ).rejects.toThrow("config_missing: CODEX_PROXY_HOST");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
