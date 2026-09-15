import {generateKeyPairSync, verify} from "node:crypto";

import {beforeEach, describe, expect, it, vi} from "vitest";

import {
  addCommentReaction,
  checkDetails,
  createAppJwt,
  createCheckRun,
  getCheckRunAppSlug,
  getInstallationToken,
  getPullRequestMetadata,
  hasCompletedReviewForHead,
  updateCheckRun,
  type TokenStorage,
} from "./github-app";
import {defaultPresentation} from "./presentation";

function privateKey(): {privatePem: string; publicPem: string} {
  const pair = generateKeyPairSync("rsa", {modulusLength: 2048});
  return {
    privatePem: pair.privateKey.export({type: "pkcs8", format: "pem"}).toString(),
    publicPem: pair.publicKey.export({type: "spki", format: "pem"}).toString(),
  };
}

function pkcs1PrivateKey(): {privatePem: string; publicPem: string} {
  const pair = generateKeyPairSync("rsa", {modulusLength: 2048});
  return {
    privatePem: pair.privateKey.export({type: "pkcs1", format: "pem"}).toString(),
    publicPem: pair.publicKey.export({type: "spki", format: "pem"}).toString(),
  };
}

class FakeStorage implements TokenStorage {
  readonly values = new Map<string, unknown>();

  async get<T>(key: string): Promise<T | undefined> {
    return this.values.get(key) as T | undefined;
  }

  async put<T>(key: string, value: T): Promise<void> {
    this.values.set(key, value);
  }
}

describe("GitHub App JWT", () => {
  it("signs RS256 with a bounded, backdated claim window", async () => {
    const key = privateKey();
    const jwt = await createAppJwt("12345", key.privatePem, 2_000_000_000_000);
    const [header, payload, signature] = jwt.split(".");
    expect(JSON.parse(Buffer.from(header, "base64url").toString())).toEqual({
      alg: "RS256",
      typ: "JWT",
    });
    expect(JSON.parse(Buffer.from(payload, "base64url").toString())).toEqual({
      iat: 1_999_999_940,
      exp: 2_000_000_540,
      iss: "12345",
    });
    expect(
      verify(
        "RSA-SHA256",
        Buffer.from(`${header}.${payload}`),
        key.publicPem,
        Buffer.from(signature, "base64url"),
      ),
    ).toBe(true);
  });

  it("accepts the PKCS#1 PEM shape issued for GitHub Apps", async () => {
    const key = pkcs1PrivateKey();
    const jwt = await createAppJwt("12345", key.privatePem, 2_000_000_000_000);
    const [header, payload, signature] = jwt.split(".");
    expect(
      verify(
        "RSA-SHA256",
        Buffer.from(`${header}.${payload}`),
        key.publicPem,
        Buffer.from(signature, "base64url"),
      ),
    ).toBe(true);
  });
});

describe("installation token cache", () => {
  it("requests a repository-scoped token and reuses it before expiry minus five minutes", async () => {
    const key = privateKey();
    const storage = new FakeStorage();
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        repository_ids: [23],
        permissions: {checks: "write", contents: "read", pull_requests: "write"},
      });
      return Response.json(
        {token: "ghs_scoped", expires_at: "2033-05-18T04:33:20.000Z"},
        {status: 201},
      );
    });
    const options = {
      storage,
      appId: "12345",
      privateKey: key.privatePem,
      installationId: 17,
      repoId: 23,
      nowMs: 2_000_000_000_000,
      fetcher,
    };
    await expect(getInstallationToken(options)).resolves.toBe("ghs_scoped");
    await expect(getInstallationToken({...options, nowMs: 2_000_000_100_000})).resolves.toBe(
      "ghs_scoped",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refreshes a token at expiry minus five minutes", async () => {
    const key = privateKey();
    const storage = new FakeStorage();
    storage.values.set("github-token:17:23", {
      token: "old",
      expiresAtMs: 2_000_000_300_000,
    });
    const fetcher = vi.fn(async () =>
      Response.json(
        {token: "fresh", expires_at: "2033-05-18T04:43:20.000Z"},
        {status: 201},
      ),
    );
    await expect(
      getInstallationToken({
        storage,
        appId: "12345",
        privateKey: key.privatePem,
        installationId: 17,
        repoId: 23,
        nowMs: 2_000_000_000_000,
        fetcher,
      }),
    ).resolves.toBe("fresh");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("Check Runs", () => {
  it("creates an in-progress review check", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        name: "rvw",
        head_sha: "a".repeat(40),
        status: "in_progress",
        external_id: "job-1",
      });
      return Response.json({id: 99, html_url: "https://github.com/acme/rvw/runs/99"}, {status: 201});
    });
    await expect(
      createCheckRun(
        "ghs_scoped",
        {owner: "acme", repo: "rvw", headSha: "a".repeat(40), jobId: "job-1"},
        fetcher,
      ),
    ).resolves.toEqual({id: 99, htmlUrl: "https://github.com/acme/rvw/runs/99"});
  });

  it("updates a terminal check with the requested conclusion", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("PATCH");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        status: "completed",
        conclusion: "neutral",
        output: {title: "rvw review could not complete", summary: "sandbox crashed"},
      });
      return Response.json({id: 99}, {status: 200});
    });
    await updateCheckRun(
      "ghs_scoped",
      {
        owner: "acme",
        repo: "rvw",
        checkRunId: 99,
        conclusion: "neutral",
        title: "rvw review could not complete",
        summary: "sandbox crashed",
      },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("classifies GitHub 5xx as retryable", async () => {
    const fetcher = vi.fn(async () => new Response("unavailable", {status: 503}));
    await expect(
      createCheckRun(
        "ghs_scoped",
        {owner: "acme", repo: "rvw", headSha: "a".repeat(40), jobId: "job-1"},
        fetcher,
      ),
    ).rejects.toMatchObject({status: 503, retryable: true});
  });
});

it("reads bootstrap presentation with installation authorization at the base SHA", async () => {
  const {getPresentationConfig} = await import("./github-app");
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe(`https://api.github.com/repos/acme/rvw/contents/.rvw/config.yaml?ref=${"b".repeat(40)}`);
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer ghs_scoped");
    return Response.json({type: "file", encoding: "base64", content: btoa("short_name: VOOY Review\nlocale: ko")});
  });
  expect(await getPresentationConfig("ghs_scoped", {owner: "acme", repo: "rvw", baseSha: "b".repeat(40)}, fetcher)).toMatchObject({presentation: {short_name: "VOOY Review", locale: "ko"}});
});
it("reads trigger policy only from the base SHA with installation authorization", async () => {
  const {getTriggerPolicy} = await import("./github-app");
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe(`https://api.github.com/repos/acme/rvw/contents/.rvw/policies/auto.yaml?ref=${"b".repeat(40)}`);
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer scoped-token");
    return Response.json({type: "file", encoding: "base64", content: btoa("promote_to_blocker: {agreement_at_least: 2, severity_at_least: warning}\ndrop: {agreement_at_most: 1, severity_at_most: suggestion}\nblock_when: {severity_at_least: blocker}\npublish_state: comment\ntriggers: {drafts: review}")});
  });
  expect(await getTriggerPolicy("scoped-token", {owner: "acme", repo: "rvw", baseSha: "b".repeat(40)}, fetcher)).toMatchObject({policy: {drafts: "review"}});
});
it.each(["missing", "invalid", "symlink", "error", "network"])("reports %s base-ref trigger policy safely", async (kind) => {
  const {getTriggerPolicy} = await import("./github-app");
  const fetcher = vi.fn(async () => { if (kind === "network") throw new TypeError("fetch failed"); return kind === "missing" ? new Response("", {status: 404}) : kind === "error" ? new Response("", {status: 500}) : Response.json({
    type: kind === "symlink" ? "symlink" : "file", encoding: "base64", content: btoa("triggers: {mode: all}"),
  }); });
  const promise = getTriggerPolicy("token", {owner: "a", repo: "b", baseSha: "base"}, fetcher);
  if (kind === "error" || kind === "network") await expect(promise).rejects.toThrow(kind === "error" ? "HTTP 500" : "HTTP 503");
  else await expect(promise).resolves.toEqual({policy: {mode: "denylist", drafts: "skip", rules: [], dedupe_same_head: true,
    events: {pull_request: {enabled: true, actions: ["opened", "synchronize", "reopened", "ready_for_review"]},
      mention: {enabled: true, surfaces: ["issue_comment", "pull_request_review_comment"], allow: ["OWNER", "MEMBER", "COLLABORATOR"]}}},
    ...(kind === "missing" ? {} : {failure: "policy_invalid"})});
});
it.each([false, true])("upserts a completed neutral skipped check (existing=%s)", async (existing) => {
  const {upsertSkippedCheckRun} = await import("./github-app");
  const trigger = {skipped: true, rule: "release", mode: "denylist" as const, bypassed: null, policy_error: null};
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "GET") return Response.json({check_runs: existing ? [{id: 42, app: {id: 1}, external_id: "job-1:trigger-skip", status: "completed", conclusion: "neutral"}] : []});
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({status: "completed", conclusion: "neutral", output: {title: "rvw · Review skipped", summary: "Review skipped by repository policy: release."}});
    expect(body.output.text).toContain('"skipped": true');
    return Response.json({id: 42});
  });
  await upsertSkippedCheckRun("token", {owner: "acme", repo: "rvw", headSha: "a".repeat(40), jobId: "job-1", appId: "1", trigger,
    title: "rvw · Review skipped", summary: "Review skipped by repository policy: release."}, fetcher);
  expect(fetcher.mock.calls[1][1]?.method).toBe(existing ? "PATCH" : "POST");
});

describe("mention GitHub metadata", () => {
  let identity: typeof import("./github-app");
  beforeEach(async () => {
    vi.resetModules();
    identity = await import("./github-app");
  });
  it("resolves and caches the authenticated App's own id and slug with JWT authorization", async () => {
    const key = privateKey();
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      expect(String(url)).toBe("https://api.github.com/app");
      const jwt = new Headers(init?.headers).get("Authorization")!.slice("Bearer ".length);
      expect(JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString()).iss).toBe("12345");
      return Response.json({id: 12345, slug: "review-helper", name: "Display name"});
    });
    const options = {appId: "12345", privateKey: key.privatePem, fetcher};
    await expect(identity.getAuthenticatedApp(options)).resolves.toEqual({id: 12345, slug: "review-helper"});
    await expect(identity.getAuthenticatedApp({...options})).resolves.toEqual({id: 12345, slug: "review-helper"});
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("shares one authenticated identity request among simultaneous comments", async () => {
    const fetcher = vi.fn(async () => Response.json({id: 12345, slug: "review-helper"}));
    const options = {appId: "12345", privateKey: privateKey().privatePem, fetcher};
    await expect(Promise.all([
      identity.getAuthenticatedApp(options),
      identity.getAuthenticatedApp({...options}),
      identity.getAuthenticatedApp({...options}),
    ])).resolves.toEqual(Array.from({length: 3}, () => ({id: 12345, slug: "review-helper"})));
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("expires the precheck identity at five minutes and refreshes authenticated metadata", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({id: 12345, slug: "review-helper"}))
      .mockResolvedValueOnce(Response.json({id: 12345, slug: "renamed-helper"}));
    const options = {appId: "12345", privateKey: privateKey().privatePem, fetcher, nowMs: 2_000_000_000_000};
    expect(identity.getCachedAuthenticatedApp("12345")).toBeUndefined();
    await identity.getAuthenticatedApp(options);
    await expect(identity.getAuthenticatedApp({...options, nowMs: options.nowMs + 299_999}))
      .resolves.toEqual({id: 12345, slug: "review-helper"});
    expect(fetcher).toHaveBeenCalledOnce();
    expect(identity.getCachedAuthenticatedApp("12345", options.nowMs + 299_999)).toEqual({id: 12345, slug: "review-helper"});
    expect(identity.getCachedAuthenticatedApp("12345", options.nowMs + 300_000)).toBeUndefined();
    expect(identity.getCachedAuthenticatedApp("42")).toBeUndefined();
    await expect(identity.getAuthenticatedApp({...options, nowMs: options.nowMs + 300_000}))
      .resolves.toEqual({id: 12345, slug: "renamed-helper"});
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(identity.getCachedAuthenticatedApp("12345", options.nowMs + 300_000)).toEqual({id: 12345, slug: "renamed-helper"});
  });
  it("does not expose an expired slug after refresh failure and retries the next request", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({id: 12345, slug: "review-helper"}))
      .mockResolvedValueOnce(new Response("unavailable", {status: 503}))
      .mockResolvedValueOnce(Response.json({id: 12345, slug: "review-helper"}));
    const options = {appId: "12345", privateKey: privateKey().privatePem, fetcher, nowMs: 2_000_000_000_000};
    await identity.getAuthenticatedApp(options);
    const expired = {...options, nowMs: options.nowMs + 300_000};
    await expect(identity.getAuthenticatedApp(expired)).rejects.toMatchObject({status: 503});
    expect(identity.getCachedAuthenticatedApp("12345", expired.nowMs)).toBeUndefined();
    await expect(identity.getAuthenticatedApp(expired)).resolves.toEqual({id: 12345, slug: "review-helper"});
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it("does not cache failed cold identity requests", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response("unavailable", {status: 503}))
      .mockResolvedValueOnce(Response.json({id: 12345, slug: "review-helper"}));
    const options = {appId: "12345", privateKey: privateKey().privatePem, fetcher};
    await expect(identity.getAuthenticatedApp(options)).rejects.toMatchObject({status: 503});
    expect(identity.getCachedAuthenticatedApp("12345")).toBeUndefined();
    await expect(identity.getAuthenticatedApp(options)).resolves.toEqual({id: 12345, slug: "review-helper"});
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each([{id: 42, slug: "review-helper"}, {id: "12345", slug: "review-helper"}, {id: 12345, slug: "unsafe[bot]"}])("rejects mismatched or unsafe App metadata %j", async (metadata) => {
    await expect(identity.getAuthenticatedApp({appId: "12345", privateKey: privateKey().privatePem,
      fetcher: async () => Response.json(metadata)})).rejects.toThrow(/App identity/);
  });
  const pull = {state: "open", number: 7, head: {sha: "a".repeat(40), ref: "feature"},
    base: {sha: "b".repeat(40), ref: "main"}, draft: true, user: {login: "maintainer"},
    labels: [{name: "needs-review"}], title: "A change"};
  it("reads current PR head, base and state with the installation token", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      expect(String(url)).toBe("https://api.github.com/repos/acme/rockets/pulls/7");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer installation-token");
      return Response.json({...pull, irrelevant: "ignored"});
    });
    await expect(getPullRequestMetadata("installation-token", {owner: "acme", repo: "rockets", prNumber: 7}, fetcher))
      .resolves.toEqual(pull);
  });
  it.each([{head: {sha: "bad", ref: "feature"}}, {number: 8}, {draft: "false"}, {state: "unknown"}, {labels: ["bad"]}])(
    "rejects invalid PR metadata %j", async (override) => {
      await expect(getPullRequestMetadata("token", {owner: "acme", repo: "rockets", prNumber: 7},
        async () => Response.json({...pull, ...override}))).rejects.toThrow(/pull request/);
    });
});

describe("optional issue reaction permissions", () => {
  it("separates a reaction-capable token from the cached review token", async () => {
    const storage = new FakeStorage();
    storage.values.set("github-token:17:23", {token: "review-only", expiresAtMs: 2_000_001_000_000});
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body)).permissions).toEqual({checks: "write", contents: "read", pull_requests: "write", issues: "write"});
      return Response.json({token: "reaction-capable", expires_at: "2033-05-18T04:43:20.000Z"});
    });
    const options = {storage, appId: "12345", privateKey: privateKey().privatePem,
      installationId: 17, repoId: 23, nowMs: 2_000_000_000_000, fetcher};
    await expect(getInstallationToken({...options, issuesWrite: true})).resolves.toBe("reaction-capable");
    await expect(getInstallationToken({...options, issuesWrite: true})).resolves.toBe("reaction-capable");
    await expect(getInstallationToken(options)).resolves.toBe("review-only");
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it.each([403, 422])("falls back to existing review permissions when Issues write is refused with %s", async (status) => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const permissions = JSON.parse(String(init?.body)).permissions;
      return permissions.issues === "write" ? new Response("", {status})
        : Response.json({token: "review-only", expires_at: "2033-05-18T04:43:20.000Z"});
    });
    await expect(getInstallationToken({storage: new FakeStorage(), appId: "12345", privateKey: privateKey().privatePem,
      installationId: 17, repoId: 23, nowMs: 2_000_000_000_000, issuesWrite: true, fetcher})).resolves.toBe("review-only");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each([["issue_comment", "issues"], ["pull_request_review_comment", "pulls"]] as const)(
    "reacts eyes on %s using the correct endpoint", async (surface, route) => {
      const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        expect(String(url)).toBe(`https://api.github.com/repos/acme/rockets/${route}/comments/71/reactions`);
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({content: "eyes"});
        return Response.json({id: 1}, {status: 201});
      });
      await addCommentReaction("token", {owner: "acme", repo: "rockets", commentId: 71, surface}, fetcher);
      expect(fetcher).toHaveBeenCalledOnce();
    });
  it("exposes a forbidden reaction for the webhook's best-effort acknowledgment", async () => {
    await expect(addCommentReaction("token", {owner: "acme", repo: "rockets", commentId: 71, surface: "issue_comment"},
      async () => new Response("", {status: 403}))).rejects.toMatchObject({status: 403});
  });
});

describe("completed review evidence", () => {
  const input = {owner: "acme", repo: "rockets", headSha: "a".repeat(40), appId: "12345",
    installationId: 17, repoId: 23, prNumber: 7};
  const jobId = `17:23:7:${input.headSha}`;
  const facts = {job_id: jobId, reason: "rvw run passed", trigger: {skipped: false},
    lanes: {dispatched: 1, valid: 1}, artifact_key: `jobs/${jobId}/`};
  const completed = {id: 17, app: {id: 12345}, head_sha: input.headSha, external_id: jobId,
    status: "completed", conclusion: "success", output: {text: checkDetails(facts, defaultPresentation())}};
  it.each(["success", "failure", "neutral"])("recognizes actual completed reviews with %s conclusion", async (conclusion) => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed, conclusion}]})))
      .resolves.toBe(true);
  });
  it.each([
    {app: {id: 888}}, {app: {id: "12345"}}, {head_sha: "b".repeat(40)}, {status: "in_progress"},
    {external_id: `${jobId}:trigger-skip`},
    {output: {text: checkDetails({...facts, trigger: {skipped: true}}, defaultPresentation())}},
    {output: {text: checkDetails({...facts, reason: "process_invalid: missing manifest"}, defaultPresentation())}},
    {output: {text: checkDetails({...facts, lanes: {valid: 0}}, defaultPresentation())}},
    {output: {text: checkDetails({...facts, review_completed: false}, defaultPresentation())}},
    {output: {text: "unstructured success"}},
  ])("does not mistake unrelated, skipped, or failed checks for a completed review %j", async (override) => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed, ...override}]})))
      .resolves.toBe(false);
  });
  it("recognizes explicit completion evidence without detailed checks", async () => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      conclusion: "neutral", output: {text: checkDetails({review_completed: true}, defaultPresentation())}}]}))).resolves.toBe(true);
  });
  it.each([
    {external_id: `17:23:8:${input.headSha}`, pull_requests: [{number: 8}]},
    {external_id: `18:23:7:${input.headSha}`},
    {external_id: `17:24:7:${input.headSha}`},
    {external_id: "unrelated-job", pull_requests: [{number: "7"}]},
    {external_id: "unrelated-job", pull_requests: []},
  ])("does not suppress this PR with completion evidence for another identity %j", async (override) => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      ...override, output: {text: checkDetails({review_completed: true}, defaultPresentation())}}]}))).resolves.toBe(false);
  });
  it("recognizes this PR through the exact external identity when pull_requests is absent", async () => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [completed]})))
      .resolves.toBe(true);
  });
  it.each([false, true])("does not use ambiguous pull_requests without a recoverable job identity (explicit=%s)", async (explicit) => {
    const externalId = "legacy-review-id";
    const output = checkDetails(explicit ? {review_completed: true} : {...facts,
      job_id: externalId, artifact_key: `jobs/${externalId}/`}, defaultPresentation());
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      external_id: externalId, pull_requests: [{number: 8}, {number: 7}], output: {text: output}}]})))
      .resolves.toBe(false);
  });
  it.each([false, true])("recovers this PR from structured job facts with an unrecognized external ID (explicit=%s)", async (explicit) => {
    const output = checkDetails({...facts, ...(explicit ? {review_completed: true} : {})}, defaultPresentation());
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      external_id: "legacy-review-id", pull_requests: [{number: 8}], output: {text: output}}]})))
      .resolves.toBe(true);
  });
  it.each(["external_id", "job_id", "artifact_key"])("rejects contradictory %s despite matching evidence elsewhere", async (field) => {
    const otherJobId = `17:23:8:${input.headSha}`;
    const outputFacts = {...facts, review_completed: true,
      ...(field === "job_id" ? {job_id: otherJobId} : {}),
      ...(field === "artifact_key" ? {artifact_key: `jobs/${otherJobId}/`} : {})};
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      ...(field === "external_id" ? {external_id: otherJobId} : {}),
      pull_requests: [{number: 7}, {number: 8}], output: {text: checkDetails(outputFacts, defaultPresentation())}}]})))
      .resolves.toBe(false);
  });
  it("rejects legacy facts identifying another PR even with this PR's external ID", async () => {
    const otherJobId = `17:23:8:${input.headSha}`;
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      pull_requests: [{number: 7}], output: {text: checkDetails({...facts,
        job_id: otherJobId, artifact_key: `jobs/${otherJobId}/`}, defaultPresentation())}}]})))
      .resolves.toBe(false);
  });
  it("still excludes skip checks associated with this PR", async () => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: [{...completed,
      external_id: `${jobId}:trigger-skip`, pull_requests: [{number: 7}],
      output: {text: checkDetails({review_completed: true}, defaultPresentation())}}]}))).resolves.toBe(false);
  });
  it("returns no completion when GitHub has no visible history", async () => {
    await expect(hasCompletedReviewForHead("token", input, async () => Response.json({check_runs: []})))
      .resolves.toBe(false);
  });
  it("exposes paginated API failure for the webhook's fail-open handler", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({check_runs: Array.from({length: 100}, () => ({...completed,
        status: "in_progress"}))}))
      .mockResolvedValueOnce(new Response("unavailable", {status: 503}));
    await expect(hasCompletedReviewForHead("token", input, fetcher)).rejects.toMatchObject({status: 503});
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("scans every page with filter=all so newer skips cannot hide a completed review", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => {
      const request = new URL(String(url));
      expect(request.searchParams.get("filter")).toBe("all");
      expect(request.searchParams.get("app_id")).toBe("12345");
      return request.searchParams.get("page") === "1"
        ? Response.json({check_runs: Array.from({length: 100}, () => ({...completed, app: {id: 888}})), total_count: 101})
        : Response.json({check_runs: [completed], total_count: 101});
    });
    await expect(hasCompletedReviewForHead("token", input, fetcher)).resolves.toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each(["in_progress", "completed"])("never overwrites an existing %s review check when recording a skip", async (status) => {
    const {upsertSkippedCheckRun} = await import("./github-app");
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "GET") return Response.json({check_runs: [{...completed, status}]});
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body)).external_id).toBe("job-1:trigger-skip");
      return Response.json({id: 18});
    });
    await upsertSkippedCheckRun("token", {...input, jobId: "job-1", title: "Skipped", summary: "Policy skipped",
      trigger: {skipped: true, rule: null, mode: "denylist", bypassed: null, policy_error: null}}, fetcher);
  });
});
it.each(["missing", "malformed", "symlink"])("uses safe bootstrap defaults for %s config", async (kind) => {
  const {getPresentationConfig} = await import("./github-app");
  const fetcher = vi.fn(async () => kind === "missing" ? new Response("", {status: 404}) : Response.json({
    type: kind === "symlink" ? "symlink" : "file", encoding: "base64", content: btoa("locale: fr"),
  }));
  expect(await getPresentationConfig("token", {owner: "a", repo: "b", baseSha: "base"}, fetcher)).toEqual({
    presentation: {display_name: "rvw", short_name: "rvw", locale: "en", footer: null,
      voice: {audience: "engineers", register: "formal", guidance: null,
        examples: [], allowed_terms: []}, synthesis: {enabled: true}},
    ...(kind === "missing" ? {} : {failure: "presentation_config_invalid"}),
  });
});
it("uses configured bootstrap names and puts the job id only in structured text", async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({name: "VOOY Review", external_id: "job-private", output: {
      title: "VOOY Review System · 검토 중", summary: "검토 중입니다.",
    }});
    expect(body.output.summary).not.toContain("job-private");
    expect(body.output.text).toContain("job-private");
    return Response.json({id: 42});
  });
  await createCheckRun("token", {owner: "a", repo: "b", headSha: "head", jobId: "job-private",
    presentation: {display_name: "VOOY Review System", short_name: "VOOY Review", locale: "ko", footer: null,
      voice: {audience: "engineers", register: "formal", guidance: null,
        examples: [], allowed_terms: []}, synthesis: {enabled: true}}}, fetcher);
});
it("updates a check name and diagnostic text", async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toMatchObject({name: "New review", output: {text: "diagnostics"}});
    return Response.json({id: 42});
  });
  await updateCheckRun("token", {owner: "a", repo: "b", checkRunId: 42, conclusion: "success", title: "Done", summary: "Complete", name: "New review", text: "diagnostics"}, fetcher);
});

describe("check-run App slug", () => {
  const input = {owner: "acme", repo: "rockets", headSha: "a".repeat(40), jobId: "job-1"};
  it("returns the App slug from the creation response when GitHub reports one", async () => {
    const fetcher = vi.fn(async () => Response.json({id: 7, html_url: "https://example.test/c/7",
      app: {id: 1, slug: "review-app"}}, {status: 201}));
    await expect(createCheckRun("token", input, fetcher)).resolves.toEqual({id: 7, htmlUrl: "https://example.test/c/7", appSlug: "review-app"});
  });
  it("omits the slug when the response has none or it is not a safe identifier", async () => {
    const none = vi.fn(async () => Response.json({id: 7}, {status: 201}));
    await expect(createCheckRun("token", input, none)).resolves.toEqual({id: 7});
    const unsafe = vi.fn(async () => Response.json({id: 7, app: {slug: "bad slug[bot]"}}, {status: 201}));
    await expect(createCheckRun("token", input, unsafe)).resolves.toEqual({id: 7});
  });
  it("reads the slug back from an existing check run", async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => {
      expect(String(url)).toBe("https://api.github.com/repos/acme/rockets/check-runs/42");
      return Response.json({id: 42, app: {slug: "review-app"}});
    });
    await expect(getCheckRunAppSlug("token", {owner: "acme", repo: "rockets", checkRunId: 42}, fetcher)).resolves.toBe("review-app");
    const failing = vi.fn(async () => new Response("", {status: 500}));
    await expect(getCheckRunAppSlug("token", {owner: "acme", repo: "rockets", checkRunId: 42}, failing)).rejects.toThrow(/HTTP 500/);
  });
});
