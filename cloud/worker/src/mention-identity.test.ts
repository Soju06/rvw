import {createHmac, generateKeyPairSync} from "node:crypto";
import MarkdownIt from "markdown-it";
import {afterEach, beforeEach, expect, it, vi} from "vitest";

const key = generateKeyPairSync("rsa", {modulusLength: 2048}).privateKey.export({type: "pkcs8", format: "pem"}).toString();
const env = {GITHUB_APP_ID: "901", GITHUB_APP_PRIVATE_KEY: key, GITHUB_WEBHOOK_SECRET: "offline-secret"} as Env;

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

beforeEach(() => vi.resetModules());
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("reuses authenticated public App identity across actual webhook requests for five minutes", async () => {
  const parse = vi.spyOn(MarkdownIt.prototype, "parse");
  let now = 2_000_000_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  const appFetch = vi.fn(async (url: string) => {
    expect(url).toBe("https://api.github.com/app");
    return Response.json({id: 901, slug: "review-helper"});
  });
  vi.stubGlobal("fetch", appFetch);
  // Contains the literal slug, but not a whole mention: no installation token is needed.
  expect((await deliver("@review-helperbot")).status).toBe(204);
  expect((await deliver("@REVIEW-HELPERbot")).status).toBe(204);
  expect(appFetch).toHaveBeenCalledTimes(1);
  now += 5 * 60_000;
  expect((await deliver("@review-helperbot")).status).toBe(204);
  expect(appFetch).toHaveBeenCalledTimes(2);
  expect(parse).toHaveBeenCalledTimes(3);
});

it("ordinary discussion makes zero real App API calls and zero parses even when App API is down", async () => {
  const appFetch = vi.fn(async () => new Response(null, {status: 503}));
  vi.stubGlobal("fetch", appFetch);
  const parse = vi.spyOn(MarkdownIt.prototype, "parse");
  expect((await deliver("Thanks, this is fixed.")).status).toBe(204);
  expect(appFetch).not.toHaveBeenCalled();
  expect(parse).not.toHaveBeenCalled();
});

it("actual App API failure for a possible cold-isolate mention returns 204 with a structured log", async () => {
  const appFetch = vi.fn(async () => new Response(null, {status: 503}));
  vi.stubGlobal("fetch", appFetch);
  const log = vi.spyOn(console, "log");
  expect((await deliver("@review-helper review")).status).toBe(204);
  expect(appFetch).toHaveBeenCalledOnce();
  expect(log).toHaveBeenCalledWith(expect.stringContaining('"reason":"app_identity_unavailable"'));
});
