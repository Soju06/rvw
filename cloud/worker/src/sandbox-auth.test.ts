import {describe, expect, it, vi} from "vitest";

import {
  REASONING_EFFORT_VALUES,
  botLoginForAppSlug,
  buildGitCloneUrl,
  buildReviewProcessEnv,
  buildRvwRunInvocation,
  codexPolicyArguments,
  credentialKindForHost,
  injectCodexCredential,
  injectGitHubApiCredential,
  injectGitHubCloneCredential,
  isReasoningEffort,
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
    expect(processEnv).not.toHaveProperty("RVW_GITHUB_LOGIN");
    expect(JSON.stringify(processEnv)).not.toContain("ghs_");
  });

  it("passes the App's own bot login so Python can recognise its threads", () => {
    expect(botLoginForAppSlug("review-app")).toBe("review-app[bot]");
    expect(buildReviewProcessEnv("codex.example", botLoginForAppSlug("review-app"))).toMatchObject({
      RVW_GITHUB_LOGIN: "review-app[bot]",
    });
    expect(buildReviewProcessEnv("codex.example", "")).not.toHaveProperty("RVW_GITHUB_LOGIN");
  });

  it("runs the canonical command with webhook anchors and the artifact root", () => {
    const options = {owner: "acme", repo: "rockets", prNumber: 42,
      baseSha: "b".repeat(40), headSha: "a".repeat(40), deadlineSeconds: 900};
    const command = buildRvwRunInvocation(options);
    expect(command).toContain("python -m rvw.container_entrypoint run ");
    expect(command).toContain("--target 'https://github.com/acme/rockets/pull/42'");
    expect(command).toContain(`--base-ref '${options.baseSha}' --head-ref '${options.headSha}'`);
    expect(command).toContain("--out '/workspace/result' --deadline 900 --policy auto --publish github-review --json");
    expect(buildRvwRunInvocation({...options, publish: "github-comment"})).toContain("--publish github-comment --json");
    const checksOnly = buildRvwRunInvocation({...options, publish: null});
    expect(checksOnly).toContain("--deadline 900 --policy auto --json");
    expect(checksOnly).not.toContain("--publish");
    expect(command).not.toContain("GH_REPO");
    expect(command).not.toContain("--repo-dir");
    expect(() => buildRvwRunInvocation({...options, prNumber: 0})).toThrow(/positive integer/);
    expect(() => buildRvwRunInvocation({...options, owner: "bad owner"})).toThrow(/path components/);
    expect(() => buildRvwRunInvocation({...options, headSha: "moving"})).toThrow(/anchors/);
  });

  it("always passes an explicit bounded --deadline instead of relying on the CLI default", () => {
    const options = {owner: "acme", repo: "rockets", prNumber: 42,
      baseSha: "b".repeat(40), headSha: "a".repeat(40), deadlineSeconds: 1500};
    expect(buildRvwRunInvocation(options)).toMatch(/ --deadline 1500 --policy auto /);
    expect(buildRvwRunInvocation({...options, deadlineSeconds: 1})).toContain(" --deadline 1 ");
    expect(buildRvwRunInvocation({...options, deadlineSeconds: 1800})).toContain(" --deadline 1800 ");
    for (const deadlineSeconds of [0, -1, 1801, 900.5, Number.NaN]) {
      expect(() => buildRvwRunInvocation({...options, deadlineSeconds})).toThrow(/review deadline/);
    }
  });
});

describe("Codex runtime policy overrides", () => {
  const options = {owner: "acme", repo: "rockets", prNumber: 42,
    baseSha: "b".repeat(40), headSha: "a".repeat(40), deadlineSeconds: 900};

  it("names exactly the nine Codex 0.152.0 named efforts and rejects everything else", () => {
    expect([...REASONING_EFFORT_VALUES]).toEqual(
      ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"]);
    for (const value of REASONING_EFFORT_VALUES) expect(isReasoningEffort(value)).toBe(true);
    for (const value of ["turbo", "Max", "MAX", " high", "high ", "", "custom:foo", 3, null, undefined]) {
      expect(isReasoningEffort(value)).toBe(false);
    }
  });

  it("omits both flags when no override is supplied", () => {
    const command = buildRvwRunInvocation(options);
    expect(command.endsWith("--publish github-review --json")).toBe(true);
    expect(command).not.toContain("--model");
    expect(command).not.toContain("--reasoning-effort");
    expect(codexPolicyArguments(undefined, undefined)).toBe("");
  });

  it("appends shell-quoted --model and --reasoning-effort after --json, each only when supplied", () => {
    expect(buildRvwRunInvocation({...options, model: "gpt-6-astra", reasoningEffort: "high"}))
      .toMatch(/ --publish github-review --json --model 'gpt-6-astra' --reasoning-effort 'high'$/);
    const modelOnly = buildRvwRunInvocation({...options, model: "gpt-6-astra"});
    expect(modelOnly.endsWith("--json --model 'gpt-6-astra'")).toBe(true);
    expect(modelOnly).not.toContain("--reasoning-effort");
    const effortOnly = buildRvwRunInvocation({...options, reasoningEffort: "medium"});
    expect(effortOnly.endsWith("--json --reasoning-effort 'medium'")).toBe(true);
    expect(effortOnly).not.toContain("--model");
    expect(buildRvwRunInvocation({...options, model: "it's"})).toContain("--model 'it'\\''s'");
  });

  it.each(["", "   ", "\t"])("rejects an empty or whitespace model %#", (model) => {
    expect(() => buildRvwRunInvocation({...options, model})).toThrow(/model override must be a non-empty string/);
    expect(() => codexPolicyArguments(model, undefined)).toThrow(/model override/);
  });

  it.each(["turbo", "Max", "", "high ", "custom"])("rejects the off-enum effort %s", (reasoningEffort) => {
    expect(() => buildRvwRunInvocation({...options, reasoningEffort})).toThrow(/reasoning effort override must be one of: none, minimal, low, medium, high, xhigh, max, ultra, persistent/);
    expect(() => codexPolicyArguments(undefined, reasoningEffort)).toThrow(/reasoning effort/);
  });

  it.each([...REASONING_EFFORT_VALUES])("accepts the named effort %s", (reasoningEffort) => {
    expect(buildRvwRunInvocation({...options, reasoningEffort})).toContain(`--reasoning-effort '${reasoningEffort}'`);
  });
});
