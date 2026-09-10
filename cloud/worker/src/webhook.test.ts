import {createHmac} from "node:crypto";

import {beforeEach, describe, expect, it, vi} from "vitest";
import {defaultPresentation} from "./presentation";
import {defaultTriggersPolicy, type TriggersPolicy} from "./triggers";

const mocks = vi.hoisted(() => ({
  getInstallationToken: vi.fn(async () => "installation-token"),
  getTriggerPolicy: vi.fn(), getPresentationConfig: vi.fn(),
  upsertSkippedCheckRun: vi.fn(async () => {}),
}));
vi.mock("./github-app", async (original) => ({...await original<typeof import("./github-app")>(), ...mocks}));

import {
  idempotencyKey,
  parseWebhookEvent,
  verifyWebhookSignature,
  type ReviewJobMessage,
  handleWebhook,
} from "./webhook";

const SECRET = "offline-test-secret";
const NOW = "2026-09-03T12:00:00.000Z";

function signature(body: string): string {
  return `sha256=${createHmac("sha256", SECRET).update(body).digest("hex")}`;
}

function pullRequestPayload(
  action: string,
  options: {draft?: boolean; head?: string; before?: string} = {},
): Record<string, unknown> {
  return {
    action,
    before: options.before,
    installation: {id: 17},
    repository: {id: 23, name: "rvw", full_name: "acme/rvw", owner: {login: "acme"}},
    pull_request: {
      number: 42,
      draft: options.draft ?? false,
      user: {login: "github-actions[bot]"},
      title: "chore(release): version packages", labels: [{name: "🧹 Chore"}],
      head: {sha: options.head ?? "a".repeat(40), ref: "changeset-release/main"},
      base: {sha: "b".repeat(40), ref: "main"},
    },
  };
}

describe("verifyWebhookSignature", () => {
  it("accepts the exact signed bytes", async () => {
    const body = JSON.stringify(pullRequestPayload("opened"));
    await expect(verifyWebhookSignature(body, signature(body), SECRET)).resolves.toBe(true);
  });

  it("verifies the original UTF-8 request bytes", async () => {
    const bytes = new TextEncoder().encode('{"label":"검토"}');
    const provided = `sha256=${createHmac("sha256", SECRET).update(bytes).digest("hex")}`;
    await expect(verifyWebhookSignature(bytes, provided, SECRET)).resolves.toBe(true);
  });

  it.each([null, "sha256=deadbeef", "sha1=deadbeef"])(
    "rejects missing or invalid signatures",
    async (provided) => {
      const body = JSON.stringify(pullRequestPayload("opened"));
      await expect(verifyWebhookSignature(body, provided, SECRET)).resolves.toBe(false);
    },
  );

  it("fails closed when the webhook secret is empty", async () => {
    const body = JSON.stringify(pullRequestPayload("opened"));
    const emptySecretSignature = `sha256=${createHmac("sha256", "").update(body).digest("hex")}`;
    await expect(verifyWebhookSignature(body, emptySecretSignature, "")).resolves.toBe(false);
  });

  it("maps a replay to the same durable identity", async () => {
    const body = JSON.stringify(pullRequestPayload("opened"));
    const provided = signature(body);
    expect(await verifyWebhookSignature(body, provided, SECRET)).toBe(true);
    expect(await verifyWebhookSignature(body, provided, SECRET)).toBe(true);

    const first = parseWebhookEvent("pull_request", "delivery-1", JSON.parse(body), NOW);
    const replay = parseWebhookEvent("pull_request", "delivery-1", JSON.parse(body), NOW);
    expect(first).toEqual(replay);
  });
});

describe("parseWebhookEvent", () => {
  it.each(["opened", "reopened", "ready_for_review"])(
    "accepts pull_request.%s",
    (action) => {
      const parsed = parseWebhookEvent(
        "pull_request",
        "delivery-1",
        pullRequestPayload(action, {draft: action === "ready_for_review"}),
        NOW,
      );
      expect(parsed.kind).toBe("enqueue");
    },
  );

  it("captures the prior head for synchronize supersession", () => {
    const previous = "c".repeat(40);
    const parsed = parseWebhookEvent(
      "pull_request",
      "delivery-sync",
      pullRequestPayload("synchronize", {before: previous}),
      NOW,
    );
    expect(parsed).toMatchObject({
      kind: "enqueue",
      message: {previousHeadSha: previous, event: "pull_request.synchronize"},
    });
  });

  it.each([
    ["pull_request", pullRequestPayload("closed")],
    ["issues", {action: "opened"}],
  ])("ignores unsupported events", (eventName, payload) => {
    expect(parseWebhookEvent(eventName, "delivery-ignore", payload, NOW)).toEqual({
      kind: "ignore",
    });
  });

  it("accepts check_run.rerequested for its associated PR head", () => {
    const payload = {
      action: "rerequested",
      installation: {id: 17},
      repository: {id: 23, name: "rvw", full_name: "acme/rvw", owner: {login: "acme"}},
      check_run: {
        head_sha: "d".repeat(40),
        pull_requests: [
          {number: 42, head: {sha: "d".repeat(40)}, base: {sha: "b".repeat(40)}},
        ],
      },
    };
    expect(parseWebhookEvent("check_run", "delivery-check", payload, NOW)).toMatchObject({
      kind: "enqueue",
      message: {event: "check_run.rerequested", prNumber: 42, headSha: "d".repeat(40)},
    });
  });

  it("rejects malformed supported payloads", () => {
    expect(() =>
      parseWebhookEvent("pull_request", "delivery-bad", {action: "opened"}, NOW),
    ).toThrow(/payload/i);
  });
});

describe("webhook repository trigger policy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getTriggerPolicy.mockResolvedValue({policy: defaultTriggersPolicy()});
    mocks.getPresentationConfig.mockResolvedValue({presentation: defaultPresentation()});
  });
  async function deliver(payload: Record<string, unknown>, event = "pull_request") {
    const body = JSON.stringify(payload);
    const send = vi.fn(); const supersede = vi.fn();
    const env = {GITHUB_WEBHOOK_SECRET: SECRET, GITHUB_APP_ID: "1", GITHUB_APP_PRIVATE_KEY: "private-key",
      RVW_REVIEW_JOBS: {send}, RVW_REVIEW_JOB: {getByName: vi.fn(() => ({supersede}))}} as unknown as Env;
    const response = await handleWebhook(new Request("https://example.test/github/webhook", {method: "POST", body,
      headers: {"X-Hub-Signature-256": signature(body), "X-GitHub-Event": event, "X-GitHub-Delivery": "delivery-1"}}), env);
    return {response, send, supersede};
  }
  it("skips matching release PRs before enqueue and creates a localized neutral check", async () => {
    const policy: TriggersPolicy = {mode: "denylist", drafts: "skip", rules: [{name: "changesets-release", authors: ["github-actions[bot]"], head_branches: ["changeset-release/*"]}]};
    mocks.getTriggerPolicy.mockResolvedValue({policy});
    mocks.getPresentationConfig.mockResolvedValue({presentation: {...defaultPresentation(), locale: "ko", short_name: "검토"}});
    const result = await deliver(pullRequestPayload("opened"));
    expect(result.response.status).toBe(202);
    expect(result.send).not.toHaveBeenCalled();
    expect(mocks.getTriggerPolicy).toHaveBeenCalledWith("installation-token", expect.objectContaining({baseSha: "b".repeat(40)}));
    expect(mocks.upsertSkippedCheckRun).toHaveBeenCalledWith("installation-token", expect.objectContaining({
      title: "검토 · 검토 건너뜀", summary: "저장소 정책에 따라 검토를 건너뛰었습니다: changesets-release.",
      trigger: {skipped: true, rule: "changesets-release", mode: "denylist", bypassed: null, policy_error: null}}));
  });
  it("rerequested bypasses filtering and records why", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: {mode: "denylist", drafts: "skip",
      rules: [{name: "changesets-release", authors: ["github-actions[bot]"]}]}});
    const payload = pullRequestPayload("rerequested");
    payload.check_run = {head_sha: "a".repeat(40), pull_requests: [{number: 42, head: {sha: "a".repeat(40)}, base: {sha: "b".repeat(40)}}]};
    const result = await deliver(payload, "check_run");
    expect(result.send).toHaveBeenCalledWith(expect.objectContaining({trigger: expect.objectContaining({bypassed: "rerequested", skipped: false})}));
    expect(mocks.upsertSkippedCheckRun).not.toHaveBeenCalled();
  });
  it("policy read failures enqueue with a visible reason", async () => {
    mocks.getTriggerPolicy.mockRejectedValue(new Error("network unavailable"));
    const result = await deliver(pullRequestPayload("opened"));
    expect(result.send).toHaveBeenCalledWith(expect.objectContaining({trigger: expect.objectContaining({policy_error: "policy_read_failed", skipped: false})}));
  });
  it("policy read failures preserve enqueue even when optional matching metadata is unavailable", async () => {
    mocks.getTriggerPolicy.mockRejectedValue(new Error("network unavailable"));
    const payload = pullRequestPayload("opened");
    const pull = payload.pull_request as Record<string, unknown>;
    delete pull.user; delete pull.labels; delete pull.title;
    const result = await deliver(payload);
    expect(result.response.status).toBe(202);
    expect(result.send).toHaveBeenCalledOnce();
  });
  it("invalid policy enqueues with policy_invalid", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: defaultTriggersPolicy(), failure: "policy_invalid"});
    const result = await deliver(pullRequestPayload("opened"));
    expect(result.send).toHaveBeenCalledWith(expect.objectContaining({trigger: expect.objectContaining({policy_error: "policy_invalid"})}));
  });
  it("drafts remain silent by default but drafts review is respected", async () => {
    const skipped = await deliver(pullRequestPayload("opened", {draft: true}));
    expect(skipped.send).not.toHaveBeenCalled();
    expect(mocks.upsertSkippedCheckRun).not.toHaveBeenCalled();
    mocks.getTriggerPolicy.mockResolvedValue({policy: {...defaultTriggersPolicy(), drafts: "review"}});
    const reviewed = await deliver(pullRequestPayload("opened", {draft: true}));
    expect(reviewed.send).toHaveBeenCalledOnce();
  });
  it("ready_for_review remains eligible even if the payload draft flag is stale", async () => {
    const result = await deliver(pullRequestPayload("ready_for_review", {draft: true}));
    expect(result.send).toHaveBeenCalledOnce();
    expect(mocks.upsertSkippedCheckRun).not.toHaveBeenCalled();
  });
  it("a skipped synchronize still supersedes the previous head", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: {mode: "denylist", drafts: "skip",
      rules: [{name: "changesets-release", head_branches: ["changeset-release/*"]}]}});
    const payload = pullRequestPayload("synchronize");
    payload.before = "c".repeat(40);
    const result = await deliver(payload);
    expect(result.send).not.toHaveBeenCalled();
    expect(result.supersede).toHaveBeenCalledWith(
      idempotencyKey(17, 23, 42, "c".repeat(40)), expect.any(String));
    expect(mocks.upsertSkippedCheckRun).toHaveBeenCalledOnce();
  });
});

describe("idempotencyKey", () => {
  it("uses installation, repository, PR, and exact head", () => {
    expect(idempotencyKey(17, 23, 42, "a".repeat(40))).toBe(
      `17:23:42:${"a".repeat(40)}`,
    );
  });

  it("is copied to jobId on messages", () => {
    const parsed = parseWebhookEvent(
      "pull_request",
      "delivery-1",
      pullRequestPayload("opened"),
      NOW,
    );
    expect(parsed.kind).toBe("enqueue");
    const message = (parsed as {kind: "enqueue"; message: ReviewJobMessage}).message;
    expect(message.jobId).toBe(message.idempotencyKey);
    expect(message).toMatchObject({attempt: 0, deliveryId: "delivery-1", enqueuedAt: NOW});
  });
});
