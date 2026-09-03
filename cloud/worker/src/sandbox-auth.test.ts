import {describe, expect, it, vi} from "vitest";

import {
  buildGitCloneUrl,
  buildReviewProcessEnv,
  buildRvwAutoInvocation,
  credentialKindForHost,
  injectCodexCredential,
  injectGitHubApiCredential,
  injectGitHubCloneCredential,
} from "./sandbox-auth";

describe("egress host matching", () => {
  it.each([
    ["codex.example", "codex.example", "codex"],
    ["api.github.com", "codex.example", "github-api"],
    ["github.com", "codex.example", "github-clone"],
    ["uploads.github.com", "codex.example", null],
  ] as const)("matches %s", (hostname, proxyHost, expected) => {
    expect(credentialKindForHost(hostname, proxyHost)).toBe(expected);
  });
});

describe("credential injection handlers", () => {
  it("injects Codex Bearer auth and logs only the hostname", async () => {
    const fetcher = vi.fn(async (request: Request) => Response.json({
      authorization: request.headers.get("Authorization"),
    }));
    const logger = vi.fn();
    const response = await injectCodexCredential(
      new Request("https://codex.example/backend-api/codex"),
      "codex-secret",
      fetcher,
      logger,
    );
    await expect(response.json()).resolves.toEqual({authorization: "Bearer codex-secret"});
    expect(logger).toHaveBeenCalledWith({
      event: "egress_credential_injected",
      hostname: "codex.example",
    });
    expect(JSON.stringify(logger.mock.calls)).not.toContain("codex-secret");
  });

  it("replaces GitHub API auth with the installation Bearer token", async () => {
    const fetcher = vi.fn(async (request: Request) => Response.json({
      authorization: request.headers.get("Authorization"),
    }));
    const request = new Request("https://api.github.com/repos/acme/rvw");
    request.headers.set("Authorization", "token placeholder-not-a-secret");
    const response = await injectGitHubApiCredential(request, "ghs_scoped", fetcher, vi.fn());
    await expect(response.json()).resolves.toEqual({authorization: "Bearer ghs_scoped"});
  });

  it("supplies Basic auth for a username-only git clone URL", async () => {
    const fetcher = vi.fn(async (request: Request) => Response.json({
      authorization: request.headers.get("Authorization"),
      url: request.url,
    }));
    const logger = vi.fn();
    const response = await injectGitHubCloneCredential(
      new Request("https://github.com/acme/rvw.git/info/refs?service=git-upload-pack"),
      "ghs_scoped",
      fetcher,
      logger,
    );
    await expect(response.json()).resolves.toEqual({
      authorization: `Basic ${btoa("x-access-token:ghs_scoped")}`,
      url: "https://github.com/acme/rvw.git/info/refs?service=git-upload-pack",
    });
    const cloneUrl = new URL(buildGitCloneUrl("acme", "rvw"));
    expect(cloneUrl.username).toBe("x-access-token");
    expect(cloneUrl.password).toBe("");
    expect(cloneUrl.href).not.toContain("ghs_scoped");
    expect(logger).toHaveBeenCalledWith({
      event: "egress_credential_injected",
      hostname: "github.com",
    });
    expect(JSON.stringify(logger.mock.calls)).not.toContain("ghs_scoped");
  });

  it("does not issue an outbound request when a credential is missing", async () => {
    const fetcher = vi.fn(async () => new Response());
    await expect(
      injectGitHubCloneCredential(new Request("https://github.com/acme/rvw.git"), "", fetcher),
    ).rejects.toThrow(/credential is unavailable/);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("review process environment", () => {
  it("contains only a placeholder Codex credential and proxy URL", () => {
    const processEnv = buildReviewProcessEnv("codex.example");
    expect(processEnv).toEqual({
      CODEX_API_KEY: "placeholder-not-a-secret",
      CODEX_BASE_URL: "https://codex.example/backend-api/codex",
    });
    expect(processEnv).not.toHaveProperty("GH_TOKEN");
    expect(processEnv).not.toHaveProperty("GITHUB_TOKEN");
    expect(JSON.stringify(processEnv)).not.toContain("ghs_");
  });

  it("materializes Codex configuration before running auto in the outer Sandbox", () => {
    expect(buildRvwAutoInvocation(42)).toBe(
      "env RVW_CODEX_SANDBOX=danger-full-access " +
        "python -m rvw.container_entrypoint auto " +
        "--target '42' --repo-dir \"$ADJ\" --json",
    );
    expect(() => buildRvwAutoInvocation(0)).toThrow(/positive integer/);
  });
});
