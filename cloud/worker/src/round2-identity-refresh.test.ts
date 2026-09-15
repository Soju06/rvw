import {createHmac, generateKeyPairSync} from "node:crypto";
import MarkdownIt from "markdown-it";
import {afterEach, beforeEach, expect, it, vi} from "vitest";

const key = generateKeyPairSync("rsa", {modulusLength: 2048}).privateKey.export({type: "pkcs8", format: "pem"}).toString();
const send = vi.fn();
const env = {RVW_REVIEW_JOBS: {send},
  RVW_REVIEW_JOB: {getByName: () => ({status: async () => null, pinMention: async (message: unknown) => message})},
  GITHUB_APP_ID: "901", GITHUB_APP_PRIVATE_KEY: key, GITHUB_WEBHOOK_SECRET: "offline-secret"} as unknown as Env;

async function deliver(body: string) {
  const {handleWebhook} = await import("./webhook");
  const raw = JSON.stringify({action: "created", installation: {id: 17},
    repository: {id: 23, name: "project", owner: {login: "acme"}},
    issue: {number: 42, pull_request: {}},
    comment: {id: 123, body, user: {type: "User", login: "maintainer"}, author_association: "MEMBER"}});
  return handleWebhook(new Request("https://example.test/github/webhook", {method: "POST", body: raw,
    headers: {"X-Hub-Signature-256": "sha256=" + createHmac("sha256", "offline-secret").update(raw).digest("hex"),
      "X-GitHub-Event": "issue_comment", "X-GitHub-Delivery": "delivery"}}), env);
}

beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

// Adapted from the reviewer's observed stale-slug probe: assert the fixed contract.
it("ROUND2 refreshes an expired App slug and accepts a new-name mention", async () => {
  let now = 2_000_000_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  let slug = "review-helper";
  const appFetch = vi.fn(async () => Response.json({id: 901, slug}));
  const fetcher = vi.fn(async (url: string) => {
    if (url === "https://api.github.com/app") return appFetch();
    if (url.endsWith("/access_tokens")) return Response.json({token: "installation-token", expires_at: new Date(now + 60 * 60_000).toISOString()});
    if (url.endsWith("/pulls/42")) return Response.json({number: 42, state: "open", draft: false,
      title: "A change", labels: [], user: {login: "author"},
      head: {sha: "a".repeat(40), ref: "feature"}, base: {sha: "b".repeat(40), ref: "main"}});
    if (url.includes("/contents/")) return new Response(null, {status: 404});
    if (url.endsWith("/reactions")) return Response.json({id: 1});
    throw new Error(`unexpected API call: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  expect((await deliver("@review-helperbot")).status).toBe(204);
  expect(appFetch).toHaveBeenCalledOnce();

  // A fresh cached slug still cheaply excludes unrelated discussion.
  fetcher.mockClear();
  const parse = vi.spyOn(MarkdownIt.prototype, "parse");
  expect((await deliver("Thanks @other")).status).toBe(204);
  expect(fetcher).not.toHaveBeenCalled();
  expect(parse).not.toHaveBeenCalled();

  now += 6 * 60_000;
  slug = "new-review-helper";
  // No-at-sign discussion must remain cheap even with expired metadata.
  expect((await deliver("Thanks, fixed.")).status).toBe(204);
  expect(fetcher).not.toHaveBeenCalled();
  expect(parse).not.toHaveBeenCalled();

  expect((await deliver("@new-review-helper review")).status).toBe(202);
  expect(send).toHaveBeenCalledOnce();
  expect(parse).toHaveBeenCalledOnce();
  expect(appFetch).toHaveBeenCalledTimes(2); // One cold lookup plus exactly one refresh.
  const {getCachedAuthenticatedApp} = await import("./github-app");
  expect(getCachedAuthenticatedApp("901")).toEqual({id: 901, slug: "new-review-helper"});
});
