import {createHmac} from "node:crypto";

import {describe, expect, it} from "vitest";

import {
  idempotencyKey,
  parseWebhookEvent,
  verifyWebhookSignature,
  type ReviewJobMessage,
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
      head: {sha: options.head ?? "a".repeat(40)},
      base: {sha: "b".repeat(40)},
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
    ["pull_request", pullRequestPayload("opened", {draft: true})],
    ["issues", {action: "opened"}],
  ])("ignores unsupported or draft events", (eventName, payload) => {
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
