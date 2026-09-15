import MarkdownIt from "markdown-it";
import {createHmac} from "node:crypto";
import {beforeEach, describe, expect, it, vi} from "vitest";
import {defaultTriggersPolicy} from "./triggers";
import {defaultPresentation} from "./presentation";

const mocks = vi.hoisted(() => ({
  getInstallationToken: vi.fn(), getTriggerPolicy: vi.fn(), getPresentationConfig: vi.fn(),
  getAuthenticatedApp: vi.fn(), getCachedAuthenticatedApp: vi.fn(), getPullRequestMetadata: vi.fn(),
  hasCompletedReviewForHead: vi.fn(), addCommentReaction: vi.fn(), upsertSkippedCheckRun: vi.fn(),
}));
vi.mock("./github-app", async (original) => ({...await original<typeof import("./github-app")>(), ...mocks}));
import {handleWebhook, matchesAppMention} from "./webhook";

const headSha = "a".repeat(40);
const baseSha = "b".repeat(40);
const pull = () => ({number: 42, state: "open", draft: false, title: "A change", labels: [],
  user: {login: "author"}, head: {sha: headSha, ref: "feature"}, base: {sha: baseSha, ref: "main"}});
function payload(event = "issue_comment", body = "@review-helper review") {
  return {action: "created", installation: {id: 17},
    repository: {id: 23, name: "project", owner: {login: "acme"}},
    ...(event === "issue_comment" ? {issue: {number: 42, pull_request: {url: "https://api.github.com/repos/acme/project/pulls/42"}}} : {pull_request: pull()}),
    comment: {id: 123, body, user: {type: "User", login: "maintainer"}, author_association: "MEMBER"}};
}
const status = vi.fn();
const pinMention = vi.fn();
const getByName = vi.fn();
const send = vi.fn();
async function deliver(data: unknown, event = "issue_comment", delivery = "delivery-mention") {
  const body = JSON.stringify(data);
  const signature = "sha256=" + createHmac("sha256", "test-secret").update(body).digest("hex");
  const env = {GITHUB_WEBHOOK_SECRET: "test-secret", GITHUB_APP_ID: "1", GITHUB_APP_PRIVATE_KEY: "test-key",
    RVW_REVIEW_JOBS: {send}, RVW_REVIEW_JOB: {getByName}} as unknown as Env;
  return handleWebhook(new Request("https://example.test/github/webhook", {method: "POST", body,
    headers: {"X-Hub-Signature-256": signature, "X-GitHub-Event": event, "X-GitHub-Delivery": delivery}}), env);
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  mocks.getInstallationToken.mockResolvedValue("token");
  mocks.getTriggerPolicy.mockResolvedValue({policy: defaultTriggersPolicy()});
  mocks.getPresentationConfig.mockResolvedValue({presentation: defaultPresentation()});
  mocks.getCachedAuthenticatedApp.mockReturnValue({id: 1, slug: "review-helper"});
  mocks.getAuthenticatedApp.mockResolvedValue({id: 1, slug: "review-helper"});
  mocks.getPullRequestMetadata.mockResolvedValue(pull());
  mocks.hasCompletedReviewForHead.mockResolvedValue(false);
  mocks.addCommentReaction.mockResolvedValue(undefined);
  status.mockResolvedValue(null);
  pinMention.mockImplementation(async (message) => structuredClone(message));
  getByName.mockImplementation(() => ({status, pinMention, supersede: vi.fn()}));
});

describe("mention token recognition", () => {
  it.each(["@review-helper", "@review-helper review", "@review-helper  Review", "Please @REVIEW-HELPER review!", "(@review-helper)"])("accepts %s", (body) => {
    expect(matchesAppMention(body, "review-helper")).toBe(true);
  });
  it.each(["@review-helperfoo", "email@review-helper.com", "@review-helper.com", "`@review-helper`", "``@review-helper review``",
    "- ~~~\n  @review-helper\n  ~~~", "- ```\n  @review-helper", "- ````\n  @review-helper\n  `````",
    "```md\n@review-helper\n```", "~~~\n@review-helper review\n~~~", "```\n@review-helper", "``code ` @review-helper ``"])("ignores %s", (body) => {
    expect(matchesAppMention(body, "review-helper")).toBe(false);
  });
  it("accepts prose outside fenced code", () => {
    expect(matchesAppMention("```\n@review-helper\n```\nPlease @review-helper review", "review-helper")).toBe(true);
  });
});

describe("mention webhook admission", () => {
  it.each(["issue_comment", "pull_request_review_comment"])("queues authorized %s mentions using resolved anchors", async (event) => {
    const response = await deliver(payload(event), event);
    expect(response.status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith(expect.objectContaining({headSha, baseSha, prNumber: 42,
      trigger: expect.objectContaining({source: "mention", actor: "maintainer", comment_id: 123, skipped: false})}));
    expect(mocks.getTriggerPolicy).toHaveBeenCalledWith("token", expect.objectContaining({baseSha}));
    expect(mocks.addCommentReaction).toHaveBeenCalledWith("token", expect.objectContaining({commentId: 123, surface: event}));
  });
  it("mentions bypass completed heads, draft skips and allowlist misses", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: {...defaultTriggersPolicy(), mode: "allowlist", rules: [{name: "other", authors: ["other"]}]}});
    mocks.getPullRequestMetadata.mockResolvedValue({...pull(), draft: true});
    status.mockResolvedValue({state: "completed", reviewCompleted: true});
    const response = await deliver(payload());
    expect(response.status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
    expect(mocks.hasCompletedReviewForHead).not.toHaveBeenCalled();
  });
  it.each(["Bot", "NONE", "CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", "self", "closed", "disabled", "surface", "code", "longer", "email"])("silently ignores %s", async (reason) => {
    const data = payload();
    if (reason === "Bot") data.comment.user.type = "Bot";
    else if (["NONE", "CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN"].includes(reason)) data.comment.author_association = reason;
    else if (reason === "self") data.comment.user.login = "review-helper[bot]";
    else if (reason === "closed") mocks.getPullRequestMetadata.mockResolvedValue({...pull(), state: "closed"});
    else if (reason === "disabled") { const policy = defaultTriggersPolicy(); policy.events.mention.enabled = false; mocks.getTriggerPolicy.mockResolvedValue({policy}); }
    else if (reason === "surface") { const policy = defaultTriggersPolicy(); policy.events.mention.surfaces = ["pull_request_review_comment"]; mocks.getTriggerPolicy.mockResolvedValue({policy}); }
    else if (reason === "code") data.comment.body = "```\n@review-helper\n```";
    else if (reason === "longer") data.comment.body = "@review-helperfoo";
    else if (reason === "email") data.comment.body = "email@review-helper.com";
    expect((await deliver(data)).status).toBe(204);
    expect(send).not.toHaveBeenCalled();
    expect(mocks.upsertSkippedCheckRun).not.toHaveBeenCalled();
    expect(mocks.addCommentReaction).not.toHaveBeenCalled();
  });
  it("association allow is repository policy", async () => {
    const policy = defaultTriggersPolicy(); policy.events.mention.allow = ["CONTRIBUTOR"];
    mocks.getTriggerPolicy.mockResolvedValue({policy});
    const data = payload(); data.comment.author_association = "CONTRIBUTOR";
    expect((await deliver(data)).status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
  });
  it("joins in-flight work and still reacts", async () => {
    status.mockResolvedValue({state: "running", reviewCompleted: false});
    const response = await deliver(payload());
    expect(await response.json()).toMatchObject({queued: true, trigger: {skipped: "in_flight_same_head"}});
    expect(send).toHaveBeenCalledWith(expect.objectContaining({trigger: expect.objectContaining({skipped: "in_flight_same_head"})}));
    expect(mocks.addCommentReaction).toHaveBeenCalledOnce();
  });
  it("pins a replay to its first accepted head even after the PR moves", async () => {
    await deliver(payload());
    const original = send.mock.calls[0][0];
    pinMention.mockResolvedValue(original);
    mocks.getPullRequestMetadata.mockResolvedValue({...pull(), head: {sha: "c".repeat(40), ref: "feature"}});
    send.mockClear(); getByName.mockClear();
    await deliver(payload());
    expect(send).toHaveBeenCalledWith(expect.objectContaining({headSha}));
    expect(send).not.toHaveBeenCalledWith(expect.objectContaining({headSha: "c".repeat(40)}));
  });
  it("pins the observed join so replay cannot become a rerun before queue consumption", async () => {
    status.mockResolvedValue({state: "running", reviewCompleted: false});
    await deliver(payload());
    const pinned = pinMention.mock.calls[0][0];
    expect(pinned.trigger.skipped).toBe("in_flight_same_head");
    pinMention.mockResolvedValue(pinned);
    status.mockResolvedValue({state: "completed", reviewCompleted: true});
    send.mockClear();
    await deliver(payload(), "issue_comment", "redelivery");
    expect(send).toHaveBeenCalledWith(expect.objectContaining({trigger: expect.objectContaining({skipped: "in_flight_same_head"})}));
  });
  it("reaction 403 does not cancel review", async () => {
    mocks.addCommentReaction.mockRejectedValue(Object.assign(new Error("forbidden"), {status: 403}));
    expect((await deliver(payload())).status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
  });
  it.each(["issue_comment", "pull_request_review_comment"])("ignores other %s actions with 204", async (event) => {
    expect((await deliver({...payload(event), action: "edited"}, event)).status).toBe(204);
    expect(mocks.getInstallationToken).not.toHaveBeenCalled();
  });
  it("ignores an issue that is not a pull request", async () => {
    expect((await deliver({...payload(), issue: {number: 42}})).status).toBe(204);
    expect(mocks.getInstallationToken).not.toHaveBeenCalled();
  });
});

describe("automatic event selection and completed-head admission", () => {
  function auto(action = "ready_for_review") { return {...payload(), action, pull_request: pull()}; }
  it.each(["events_disabled", "action_not_selected", "same_head_reviewed"])("records a neutral skip for %s", async (reason) => {
    const policy = defaultTriggersPolicy();
    if (reason === "events_disabled") policy.events.pull_request.enabled = false;
    if (reason === "action_not_selected") policy.events.pull_request.actions = ["opened"];
    if (reason === "same_head_reviewed") status.mockResolvedValue({state: "completed", reviewCompleted: true});
    mocks.getTriggerPolicy.mockResolvedValue({policy});
    expect((await deliver(auto(), "pull_request")).status).toBe(202);
    expect(send).not.toHaveBeenCalled();
    expect(mocks.upsertSkippedCheckRun).toHaveBeenCalledWith("token", expect.objectContaining({trigger: expect.objectContaining({skipped: reason})}));
  });
  it("uses commit checks when local state cannot establish completion", async () => {
    mocks.hasCompletedReviewForHead.mockResolvedValue(true);
    await deliver(auto(), "pull_request");
    expect(send).not.toHaveBeenCalled();
    expect(mocks.hasCompletedReviewForHead).toHaveBeenCalledWith("token", expect.objectContaining({headSha, appId: "1", installationId: 17, repoId: 23, prNumber: 42}));
  });
  it("falls back after job store failure and preserves admission on unknown evidence", async () => {
    status.mockRejectedValue(new Error("store unavailable"));
    mocks.hasCompletedReviewForHead.mockRejectedValue(new Error("checks unavailable"));
    await deliver(auto(), "pull_request");
    expect(send).toHaveBeenCalledOnce();
  });
  it("does not count a completed policy skip as a completed review", async () => {
    status.mockResolvedValue({state: "completed", reviewCompleted: false});
    await deliver(auto(), "pull_request");
    expect(mocks.hasCompletedReviewForHead).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledOnce();
  });
  it("dedupe false skips the completion lookup", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: {...defaultTriggersPolicy(), dedupe_same_head: false}});
    status.mockResolvedValue({state: "completed", reviewCompleted: true});
    await deliver(auto(), "pull_request");
    expect(send).toHaveBeenCalledOnce();
    expect(mocks.hasCompletedReviewForHead).not.toHaveBeenCalled();
  });
  it("policy errors preserve fallback even with completed-head evidence", async () => {
    mocks.getTriggerPolicy.mockResolvedValue({policy: defaultTriggersPolicy(), failure: "policy_invalid"});
    status.mockResolvedValue({state: "completed", reviewCompleted: true});
    await deliver(auto(), "pull_request");
    expect(send).toHaveBeenCalledOnce();
    expect(mocks.hasCompletedReviewForHead).not.toHaveBeenCalled();
  });
});

// The adversarial review's §3 matrix, exercised through signed webhook admission.
const mentionProbes: [string, string, boolean][] = [
  ["at start", "@slug says hi", true],
  ["middle", "please @slug take a look", true],
  ["at end", "please ping @slug", true],
  ["review", "@slug review", true],
  ["colon", "@slug: review please", true],
  ["comma", "@slug,", true],
  ["team mention suffix", "@slug/review", false],
  ["period", "@slug.", true],
  ["question mark", "@slug?", true],
  ["exclamation mark", "@slug!", true],
  ["possessive", "@slug's", true],
  ["strikethrough advisory", "~~@slug~~", true],
  ["curly quote advisory", "“@slug”", true],
  ["parentheses", "(@slug)", true],
  ["newline", "@slug\n", true],
  ["bold", "**@slug**", true],
  ["blockquote", "> @slug", false],
  ["quoted request", "> @slug review", false],
  ["quoted then fresh", "> @slug review\n\n@slug review", true],
  ["list", "- @slug", true],
  ["link", "[@slug](https://example.test)", true],
  ["angle", "<@slug>", true],
  ["uppercase", "@SLUG", true],
  ["hyphen suffix", "@slug-bot", false],
  ["plain suffix", "@slugbot", false],
  ["email-ish prefix", "foo@slug", false],
  ["inline code", "`@slug`", false],
  ["indented code", "    @slug", false],
  ["fenced code", "```\n@slug\n```", false],
  ["list fenced code", "- ```\n  @slug\n  ```", false],
  ["unterminated fence", "```\ninside\n@slug", false],
  ["HTML comment", "<!-- @slug -->", false],
  ["HTML inline", "text <!-- @slug --> text", false],
  ["HTML block", "<div>\n@slug\n</div>", false],
  ["60 KB", "x".repeat(60 * 1024) + " @slug", true],
  ["escaped mention", "\\@slug", true],
  ["formatted prefix boundary", "foo**@slug**", false],
  ["formatted suffix boundary", "@slug**bot**", false],
  ["emphasis prefix boundary", "foo*placeholder*[@slug](url)", false],
];
describe("review mention probe matrix through webhook", () => {
  it.each(mentionProbes)("%s", async (_label, body, accepted) => {
    const response = await deliver(payload("issue_comment", body.replace(/slug/ig, (slug) => slug === "SLUG" ? "REVIEW-HELPER" : "review-helper")));
    expect(response.status).toBe(accepted ? 202 : 204);
    expect(send).toHaveBeenCalledTimes(accepted ? 1 : 0);
  });
});

describe("mention precheck cost and identity failures", () => {
  it("no-at-sign discussion makes zero App calls and zero Markdown parses on a cold isolate", async () => {
    mocks.getCachedAuthenticatedApp.mockReturnValue(undefined);
    mocks.getAuthenticatedApp.mockRejectedValue(new Error("App unavailable"));
    const parse = vi.spyOn(MarkdownIt.prototype, "parse");
    expect((await deliver(payload("issue_comment", "Thanks, I will fix this."))).status).toBe(204);
    expect(mocks.getAuthenticatedApp).not.toHaveBeenCalled();
    expect(mocks.getInstallationToken).not.toHaveBeenCalled();
    expect(parse).not.toHaveBeenCalled();
  });
  it("unrelated cached-slug discussion makes zero App calls and zero parses", async () => {
    mocks.getAuthenticatedApp.mockRejectedValue(new Error("App unavailable"));
    const parse = vi.spyOn(MarkdownIt.prototype, "parse");
    expect((await deliver(payload("issue_comment", "Thanks @someone-else"))).status).toBe(204);
    expect(mocks.getAuthenticatedApp).not.toHaveBeenCalled();
    expect(mocks.getInstallationToken).not.toHaveBeenCalled();
    expect(parse).not.toHaveBeenCalled();
  });
  it.each([true, false])("App identity failure is logged and acknowledged, cached=%s", async (cached) => {
    if (!cached) mocks.getCachedAuthenticatedApp.mockReturnValue(undefined);
    mocks.getAuthenticatedApp.mockRejectedValue(new Error("App unavailable"));
    const log = vi.spyOn(console, "log");
    const parse = vi.spyOn(MarkdownIt.prototype, "parse");
    expect((await deliver(payload())).status).toBe(204);
    expect(log).toHaveBeenCalledWith(expect.stringContaining('"reason":"app_identity_unavailable"'));
    expect(parse).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });
});

describe("webhook PR-scoped check history with the real GitHub helper", () => {
  it.each(["external_id", "pull_requests", "other_pr", "wrong_app"])("checks %s evidence", async (evidence) => {
    const actual = await vi.importActual<typeof import("./github-app")>("./github-app");
    const check = {head_sha: headSha, app: {id: evidence === "wrong_app" ? 2 : 1}, status: "completed",
      external_id: `17:23:${evidence === "external_id" ? 42 : 99}:${headSha}`,
      pull_requests: [{number: evidence === "pull_requests" ? 42 : 99}],
      output: {text: '```json\n{"review_completed":true}\n```'}};
    mocks.hasCompletedReviewForHead.mockImplementation((token, input) =>
      actual.hasCompletedReviewForHead(token, input, async () => Response.json({check_runs: [check]})));
    const response = await deliver({...payload(), action: "ready_for_review", pull_request: pull()}, "pull_request");
    expect(response.status).toBe(202);
    expect(getByName).toHaveBeenCalledTimes(1);
    expect(getByName).toHaveBeenCalledWith(`17:23:42:${headSha}`);
    const completed = evidence === "external_id";
    expect(send).toHaveBeenCalledTimes(completed ? 0 : 1);
    expect(mocks.upsertSkippedCheckRun).toHaveBeenCalledTimes(completed ? 1 : 0);
  });
});

// Imported ownership regressions from the round-2 adversarial review.
describe("ROUND2 conflicting PR ownership", () => {
  it.each(["explicit", "legacy"])("must not suppress PR B from PR A review merely associated with both PRs: %s", async (kind) => {
    const actual = await vi.importActual<typeof import("./github-app")>("./github-app");
    const otherJobId = `17:23:99:${headSha}`;
    const facts = kind === "explicit" ? {review_completed: true, job_id: otherJobId} :
      {job_id: otherJobId, artifact_key: `jobs/${otherJobId}/`, lanes: {valid: 1}, reason: "rvw run passed", trigger: {skipped: false}};
    const check = {head_sha: headSha, app: {id: 1}, status: "completed", conclusion: "success",
      external_id: otherJobId, pull_requests: [{number: 99}, {number: 42}],
      output: {text: actual.checkDetails(facts, defaultPresentation())}};
    mocks.hasCompletedReviewForHead.mockImplementation((token, input) =>
      actual.hasCompletedReviewForHead(token, input, async () => Response.json({check_runs: [check]})));
    const response = await deliver({...payload(), action: "ready_for_review", pull_request: pull()}, "pull_request");
    expect(response.status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
  });
  it("admits later PR B when older PR A check lists only A", async () => {
    const actual = await vi.importActual<typeof import("./github-app")>("./github-app");
    const check = {head_sha: headSha, app: {id: 1}, status: "completed", external_id: `17:23:99:${headSha}`,
      pull_requests: [{number: 99}], output: {text: '```json\n{"review_completed":true}\n```'}};
    mocks.hasCompletedReviewForHead.mockImplementation((token, input) =>
      actual.hasCompletedReviewForHead(token, input, async () => Response.json({check_runs: [check]})));
    const response = await deliver({...payload(), action: "ready_for_review", pull_request: pull()}, "pull_request");
    expect(response.status).toBe(202);
    expect(send).toHaveBeenCalledOnce();
  });
});
