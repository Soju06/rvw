import MarkdownIt from "markdown-it";

import {getInstallationToken, getPresentationConfig, getTriggerPolicy, upsertSkippedCheckRun,
  getAuthenticatedApp, getCachedAuthenticatedApp, getPullRequestMetadata, hasCompletedReviewForHead, addCommentReaction, type TokenStorage} from "./github-app";
import {t} from "./i18n";
import {isTerminalState} from "./review-job-contract";
import {defaultPresentation} from "./presentation";
import {defaultTriggersPolicy, evaluateTrigger, parseTriggerFacts, triggerFacts, type TriggerFacts, type TriggerMetadata, type MentionSurface, type AuthorAssociation, DEFAULT_PULL_REQUEST_ACTIONS} from "./triggers";

const SHA_PATTERN = /^[0-9a-f]{40}$/;
const SIGNATURE_PATTERN = /^sha256=([0-9a-f]{64})$/;
const PULL_REQUEST_ACTIONS: ReadonlySet<string> = new Set(DEFAULT_PULL_REQUEST_ACTIONS);
const REPOSITORY_PART = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export interface ReviewJobMessage {
  jobId: string;
  idempotencyKey: string;
  installationId: number;
  repoId: number;
  owner: string;
  repo: string;
  prNumber: number;
  headSha: string;
  baseSha: string;
  previousHeadSha?: string;
  event: string;
  attempt: number;
  deliveryId: string;
  enqueuedAt: string;
  trigger?: TriggerFacts;
  dedupeSameHead?: boolean;
}

export type WebhookDecision =
  | {kind: "ignore"}
  | {kind: "enqueue"; message: ReviewJobMessage}
  | {kind: "mention"; fields: RepositoryFields; prNumber: number; surface: MentionSurface;
      commentId: number; body: string; actor: string; actorType: string; association: string;
      deliveryId: string; enqueuedAt: string};

function hexBytes(value: string): Uint8Array | null {
  const match = SIGNATURE_PATTERN.exec(value);
  if (!match) return null;
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(match[1].slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  const subtle = crypto.subtle as SubtleCrypto & {
    timingSafeEqual?: (a: ArrayBufferView, b: ArrayBufferView) => boolean;
  };
  if (subtle.timingSafeEqual !== undefined) {
    return subtle.timingSafeEqual(left, right);
  }
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left[index % left.length] ?? 0) ^ (right[index % right.length] ?? 0);
  }
  return difference === 0;
}

export async function verifyWebhookSignature(
  body: string | ArrayBuffer | Uint8Array,
  signature: string | null,
  secret: string,
): Promise<boolean> {
  if (typeof secret !== "string" || secret.length === 0) return false;
  const encoder = new TextEncoder();
  const bodyBytes =
    typeof body === "string"
      ? encoder.encode(body)
      : body instanceof Uint8Array
        ? body
        : new Uint8Array(body);
  const bodyBuffer = Uint8Array.from(bodyBytes).buffer;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    {name: "HMAC", hash: "SHA-256"},
    false,
    ["sign"],
  );
  const expected = new Uint8Array(await crypto.subtle.sign("HMAC", key, bodyBuffer));
  const provided = signature === null ? null : hexBytes(signature);
  return provided !== null && constantTimeEqual(expected, provided);
}

export function idempotencyKey(
  installationId: number,
  repoId: number,
  prNumber: number,
  headSha: string,
): string {
  return `${installationId}:${repoId}:${prNumber}:${headSha}`;
}

export function validateReviewJobMessage(value: unknown): ReviewJobMessage {
  const message = objectValue(value, "queue message");
  const installationId = positiveInteger(message.installationId, "installationId");
  const repoId = positiveInteger(message.repoId, "repoId");
  const prNumber = positiveInteger(message.prNumber, "prNumber");
  const headSha = shaValue(message.headSha, "headSha");
  const baseSha = shaValue(message.baseSha, "baseSha");
  const owner = stringValue(message.owner, "owner");
  const repo = stringValue(message.repo, "repo");
  if (!REPOSITORY_PART.test(owner) || !REPOSITORY_PART.test(repo)) {
    throw new Error("GitHub webhook payload queue message repository is unsafe");
  }
  const key = idempotencyKey(installationId, repoId, prNumber, headSha);
  if (message.jobId !== key || message.idempotencyKey !== key) {
    throw new Error("GitHub webhook payload queue message idempotency key is invalid");
  }
  if (typeof message.attempt !== "number" || !Number.isSafeInteger(message.attempt) || message.attempt < 0) {
    throw new Error("GitHub webhook payload queue message attempt is invalid");
  }
  if (message.dedupeSameHead !== undefined && typeof message.dedupeSameHead !== "boolean") {
    throw new Error("GitHub webhook payload queue message dedupeSameHead is invalid");
  }
  const previousHeadSha =
    message.previousHeadSha === undefined
      ? undefined
      : shaValue(message.previousHeadSha, "previousHeadSha");
  return {
    jobId: key,
    idempotencyKey: key,
    installationId,
    repoId,
    owner,
    repo,
    prNumber,
    headSha,
    baseSha,
    ...(previousHeadSha === undefined ? {} : {previousHeadSha}),
    event: stringValue(message.event, "event"),
    attempt: message.attempt,
    deliveryId: stringValue(message.deliveryId, "deliveryId"),
    enqueuedAt: stringValue(message.enqueuedAt, "enqueuedAt"),
    ...(message.trigger === undefined ? {} : {trigger: parseTriggerFacts(message.trigger)}),
    ...(message.dedupeSameHead === undefined ? {} : {dedupeSameHead: message.dedupeSameHead}),
  };
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`GitHub webhook payload ${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`GitHub webhook payload ${label} must be a string`);
  }
  return value;
}

function positiveInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`GitHub webhook payload ${label} must be a positive integer`);
  }
  return value;
}

function shaValue(value: unknown, label: string): string {
  const sha = stringValue(value, label);
  if (!SHA_PATTERN.test(sha)) {
    throw new Error(`GitHub webhook payload ${label} must be a full lowercase SHA`);
  }
  return sha;
}

interface RepositoryFields {
  installationId: number;
  repoId: number;
  owner: string;
  repo: string;
}

function repositoryFields(payload: Record<string, unknown>): RepositoryFields {
  const installation = objectValue(payload.installation, "installation");
  const repository = objectValue(payload.repository, "repository");
  const owner = objectValue(repository.owner, "repository.owner");
  return {
    installationId: positiveInteger(installation.id, "installation.id"),
    repoId: positiveInteger(repository.id, "repository.id"),
    owner: stringValue(owner.login, "repository.owner.login"),
    repo: stringValue(repository.name, "repository.name"),
  };
}

function messageFor(
  fields: RepositoryFields & {
    prNumber: number;
    headSha: string;
    baseSha: string;
    previousHeadSha?: string;
  },
  event: string,
  deliveryId: string,
  enqueuedAt: string,
): ReviewJobMessage {
  const key = idempotencyKey(
    fields.installationId,
    fields.repoId,
    fields.prNumber,
    fields.headSha,
  );
  return {
    jobId: key,
    idempotencyKey: key,
    installationId: fields.installationId,
    repoId: fields.repoId,
    owner: fields.owner,
    repo: fields.repo,
    prNumber: fields.prNumber,
    headSha: fields.headSha,
    baseSha: fields.baseSha,
    ...(fields.previousHeadSha === undefined
      ? {}
      : {previousHeadSha: fields.previousHeadSha}),
    event,
    attempt: 0,
    deliveryId,
    enqueuedAt,
  };
}

export function parseWebhookEvent(
  eventName: string,
  deliveryId: string,
  value: unknown,
  enqueuedAt = new Date().toISOString(),
): WebhookDecision {
  if (!["pull_request", "check_run", "issue_comment", "pull_request_review_comment"].includes(eventName)) return {kind: "ignore"};
  const checkedDeliveryId = stringValue(deliveryId, "delivery ID");
  const payload = objectValue(value, "root");
  const action = stringValue(payload.action, "action");

  if (eventName === "issue_comment" || eventName === "pull_request_review_comment") {
    if (action !== "created") return {kind: "ignore"};
    const pull = objectValue(eventName === "issue_comment" ? payload.issue : payload.pull_request, "comment pull request");
    if (eventName === "issue_comment" && (typeof pull.pull_request !== "object" || pull.pull_request === null)) return {kind: "ignore"};
    const comment = objectValue(payload.comment, "comment");
    const user = objectValue(comment.user, "comment.user");
    return {kind: "mention", fields: repositoryFields(payload), prNumber: positiveInteger(pull.number, "pull request number"),
      surface: eventName, commentId: positiveInteger(comment.id, "comment.id"),
      body: typeof comment.body === "string" ? comment.body : "", actor: stringValue(user.login, "comment.user.login"),
      actorType: stringValue(user.type, "comment.user.type"), association: stringValue(comment.author_association, "comment.author_association"),
      deliveryId: checkedDeliveryId, enqueuedAt};
  }

  if (eventName === "pull_request") {
    if (!PULL_REQUEST_ACTIONS.has(action)) return {kind: "ignore"};
    const pullRequest = objectValue(payload.pull_request, "pull_request");
    const head = objectValue(pullRequest.head, "pull_request.head");
    const base = objectValue(pullRequest.base, "pull_request.base");
    const previousHeadSha =
      action === "synchronize" && payload.before !== undefined
        ? shaValue(payload.before, "before")
        : undefined;
    return {
      kind: "enqueue",
      message: messageFor(
        {
          ...repositoryFields(payload),
          prNumber: positiveInteger(pullRequest.number, "pull_request.number"),
          headSha: shaValue(head.sha, "pull_request.head.sha"),
          baseSha: shaValue(base.sha, "pull_request.base.sha"),
          previousHeadSha,
        },
        `pull_request.${action}`,
        checkedDeliveryId,
        enqueuedAt,
      ),
    };
  }

  if (action !== "rerequested") return {kind: "ignore"};
  const checkRun = objectValue(payload.check_run, "check_run");
  if (!Array.isArray(checkRun.pull_requests) || checkRun.pull_requests.length === 0) {
    return {kind: "ignore"};
  }
  const pullRequest = objectValue(checkRun.pull_requests[0], "check_run.pull_requests[0]");
  const head = objectValue(pullRequest.head, "check_run.pull_requests[0].head");
  const base = objectValue(pullRequest.base, "check_run.pull_requests[0].base");
  const checkHead = shaValue(checkRun.head_sha, "check_run.head_sha");
  const pullHead = shaValue(head.sha, "check_run.pull_requests[0].head.sha");
  if (checkHead !== pullHead) {
    throw new Error("GitHub webhook payload check-run and pull-request heads differ");
  }
  return {
    kind: "enqueue",
    message: messageFor(
      {
        ...repositoryFields(payload),
        prNumber: positiveInteger(pullRequest.number, "check_run.pull_requests[0].number"),
        headSha: checkHead,
        baseSha: shaValue(base.sha, "check_run.pull_requests[0].base.sha"),
      },
      "check_run.rerequested",
      checkedDeliveryId,
      enqueuedAt,
    ),
  };
}

export async function handleWebhook(request: Request, env: Env): Promise<Response> {
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  if (
    !(await verifyWebhookSignature(
      bodyBytes,
      request.headers.get("X-Hub-Signature-256"),
      env.GITHUB_WEBHOOK_SECRET,
    ))
  ) {
    return Response.json({error: "invalid webhook signature"}, {status: 401});
  }

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    return Response.json({error: "invalid webhook JSON"}, {status: 400});
  }
  try {
    const decision = parseWebhookEvent(
      request.headers.get("X-GitHub-Event") ?? "",
      request.headers.get("X-GitHub-Delivery") ?? "",
      payload,
    );
    if (decision.kind === "ignore") return new Response(null, {status: 204});
    // Request-local token cache: no secrets enter queue messages or module state.
    const values = new Map<string, unknown>();
    const storage: TokenStorage = {
      get: async <T>(key: string) => values.get(key) as T | undefined,
      put: async <T>(key: string, value: T) => { values.set(key, value); },
    };
    if (decision.kind === "mention") return await handleMention(decision, env, storage);
    const message = decision.message;
    let policy = defaultTriggersPolicy();
    let token: string | undefined;
    let policyError: string | null = null;
    try {
      token = await getInstallationToken({storage, appId: env.GITHUB_APP_ID ?? "",
        privateKey: env.GITHUB_APP_PRIVATE_KEY, installationId: message.installationId, repoId: message.repoId});
      const loaded = await getTriggerPolicy(token, message);
      policy = loaded.policy;
      policyError = loaded.failure ?? null;
    } catch { policyError = "policy_read_failed"; }
    if (message.event === "check_run.rerequested") {
      message.trigger = {...triggerFacts(policy.mode), bypassed: "rerequested", policy_error: policyError};
    } else {
      const metadata = pullRequestMetadata(objectValue(payload, "root"));
      if (metadata.draft && policy.drafts === "skip") {
        return Response.json({accepted: true, queued: false}, {status: 202});
      }
      message.trigger = {...evaluateTrigger(policy, metadata), policy_error: policyError};
      if (!message.trigger.skipped && policyError === null) {
        if (!policy.events.pull_request.enabled) message.trigger.skipped = "events_disabled";
        else if (!policy.events.pull_request.actions.some((action) => message.event === `pull_request.${action}`)) {
          message.trigger.skipped = "action_not_selected";
        } else if (policy.dedupe_same_head && await completedHead(env, token!, message)) {
          message.trigger.skipped = "same_head_reviewed";
        }
      }
      if (message.trigger.skipped) return await skippedAutomatic(env, token!, message);
      // Only an explicit policy opt-out changes terminal automatic restart behavior.
      if (policyError === null) message.dedupeSameHead = policy.dedupe_same_head;
    }
    await env.RVW_REVIEW_JOBS.send(message);
    return Response.json({accepted: true, queued: true}, {status: 202});
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid webhook payload";
    return Response.json({error: message}, {status: 400});
  }
}

function pullRequestMetadata(payload: Record<string, unknown>): TriggerMetadata {
  const pull = objectValue(payload.pull_request, "pull_request");
  const head = objectValue(pull.head, "pull_request.head");
  const base = objectValue(pull.base, "pull_request.base");
  const user = typeof pull.user === "object" && pull.user !== null ? pull.user as Record<string, unknown> : {};
  return {author: typeof user.login === "string" ? user.login : null,
    headBranch: typeof head.ref === "string" ? head.ref : null, baseBranch: typeof base.ref === "string" ? base.ref : null,
    labels: Array.isArray(pull.labels) ? pull.labels.flatMap((label) => {
      if (typeof label !== "object" || label === null || typeof label.name !== "string") return [];
      return [label.name];
    }) : [],
    title: typeof pull.title === "string" ? pull.title : "",
    draft: pull.draft === true && payload.action !== "ready_for_review"};
}

const mentionMarkdown = new MarkdownIt("commonmark");

/** Preserve visible text adjacency across formatting, excluding quoted/code/HTML blocks. */
export function matchesAppMention(body: string, slug: string): boolean {
  if (!/^[a-z0-9][a-z0-9-]*$/i.test(slug) || !body.toLowerCase().includes(`@${slug.toLowerCase()}`)) return false;
  // Unparsed emphasis markers immediately before @ are not a name boundary either.
  const mention = new RegExp(`(^|[^\\p{L}\\p{N}_@./*-])@${slug}(?![\\p{L}\\p{N}_@/-]|\\.[\\p{L}\\p{N}_-]|\\[bot\\])`, "iu");
  let quoteDepth = 0;
  for (const token of mentionMarkdown.parse(body, {})) {
    if (token.type === "blockquote_open") quoteDepth += 1;
    else if (token.type === "blockquote_close") quoteDepth -= 1;
    if (quoteDepth > 0 || token.type !== "inline") continue;
    let text = "";
    for (const child of token.children ?? []) {
      if (child.type === "text") text += child.content;
      else if (["code_inline", "html_inline", "image"].includes(child.type)) {
        // Excluded content breaks adjacency; never examine its contents for a mention.
        text += "\u0000";
      } else if (["softbreak", "hardbreak"].includes(child.type)) text += "\n";
      // Opening/closing emphasis, strong and link tokens preserve text adjacency.
    }
    if (mention.test(text)) return true;
  }
  return false;
}

async function completedHead(env: Env, token: string, message: ReviewJobMessage): Promise<boolean> {
  try {
    const status = await env.RVW_REVIEW_JOB.getByName(message.idempotencyKey).status();
    if (status?.reviewCompleted === true) return true;
  } catch {
    console.log(JSON.stringify({event: "trigger.dedupe_store_unavailable", job_id: message.jobId}));
  }
  try { return await hasCompletedReviewForHead(token, {...message, appId: env.GITHUB_APP_ID ?? ""}); }
  catch {
    console.log(JSON.stringify({event: "trigger.dedupe_read_failed", job_id: message.jobId}));
    return false;
  }
}

async function skippedAutomatic(env: Env, token: string, message: ReviewJobMessage): Promise<Response> {
  const facts = message.trigger!;
  if (message.previousHeadSha !== undefined && message.previousHeadSha !== message.headSha) {
    const previousKey = idempotencyKey(message.installationId, message.repoId, message.prNumber, message.previousHeadSha);
    await env.RVW_REVIEW_JOB.getByName(previousKey).supersede(previousKey, t("superseded", "en", {job_id: message.jobId}));
  }
  let presentation = defaultPresentation();
  try { presentation = (await getPresentationConfig(token, message)).presentation; } catch { /* Safe display defaults. */ }
  const reason = typeof facts.skipped === "string" ? t(facts.skipped, presentation.locale) :
    facts.rule ?? t("trigger_no_match", presentation.locale);
  await upsertSkippedCheckRun(token, {...message, appId: env.GITHUB_APP_ID ?? "", presentation,
    title: t("check_skipped", presentation.locale, {short_name: presentation.short_name}),
    summary: t("trigger_skipped", presentation.locale, {rule: reason}), trigger: facts});
  return Response.json({accepted: true, queued: false, skipped: true, trigger: facts}, {status: 202});
}

async function handleMention(decision: Extract<WebhookDecision, {kind: "mention"}>, env: Env, storage: TokenStorage): Promise<Response> {
  const reject = (reason: string): Response => {
    console.log(JSON.stringify({event: "trigger.mention_rejected", reason, comment_id: decision.commentId,
      repo_id: decision.fields.repoId, actor: decision.actor}));
    return new Response(null, {status: 204});
  };
  if (decision.actorType.toLowerCase() === "bot") return reject("bot");
  if (!decision.body.includes("@")) return reject("no_mention");
  const cached = getCachedAuthenticatedApp(env.GITHUB_APP_ID ?? "");
  if (cached && !decision.body.toLowerCase().includes(`@${cached.slug.toLowerCase()}`)) return reject("no_mention");
  let app;
  try {
    app = await getAuthenticatedApp({appId: env.GITHUB_APP_ID ?? "", privateKey: env.GITHUB_APP_PRIVATE_KEY});
  } catch {
    return reject("app_identity_unavailable");
  }
  if (!decision.body.toLowerCase().includes(`@${app.slug.toLowerCase()}`)) return reject("no_mention");
  if (decision.actor.replace(/\[bot\]$/i, "").toLowerCase() === app.slug.toLowerCase()) return reject("app_author");
  if (!matchesAppMention(decision.body, app.slug)) return reject("no_mention");
  const tokenOptions = {storage, appId: env.GITHUB_APP_ID ?? "", privateKey: env.GITHUB_APP_PRIVATE_KEY,
    installationId: decision.fields.installationId, repoId: decision.fields.repoId};
  const token = await getInstallationToken(tokenOptions);
  const pull = await getPullRequestMetadata(token, {...decision.fields, prNumber: decision.prNumber});
  if (pull.state !== "open") return reject("closed_pr");
  let message = messageFor({...decision.fields, prNumber: decision.prNumber, headSha: pull.head.sha, baseSha: pull.base.sha},
    `${decision.surface}.created`, decision.deliveryId, decision.enqueuedAt);
  let policy = defaultTriggersPolicy();
  let policyError: string | null = null;
  try {
    const loaded = await getTriggerPolicy(token, message);
    policy = loaded.policy; policyError = loaded.failure ?? null;
  } catch { policyError = "policy_read_failed"; }
  if (!policy.events.mention.enabled) return reject("events_disabled");
  if (!policy.events.mention.surfaces.includes(decision.surface)) return reject("surface_not_selected");
  if (!policy.events.mention.allow.includes(decision.association as AuthorAssociation)) return reject("association_not_allowed");
  message.trigger = {...triggerFacts(policy.mode), source: "mention", actor: decision.actor, comment_id: decision.commentId,
    policy_error: policyError};
  const commentKey = `mention:${message.installationId}:${message.repoId}:${decision.surface}:${decision.commentId}`;
  // The queue consumer's serialized start is the only execution admission point.
  // Carry an observed join through the queue so a delayed delivery cannot become a rerun.
  const status = await env.RVW_REVIEW_JOB.getByName(message.idempotencyKey).status();
  if (status !== null && !isTerminalState(status.state)) {
    message.trigger = {...message.trigger!, skipped: "in_flight_same_head"};
  }
  message = await env.RVW_REVIEW_JOB.getByName(commentKey).pinMention(message);
  await env.RVW_REVIEW_JOBS.send(message);
  console.log(JSON.stringify({event: "trigger.mention_accepted", job_id: message.jobId, queued: true,
    trigger: message.trigger}));
  try {
    const reactionToken = decision.surface === "issue_comment" ? await getInstallationToken({...tokenOptions, issuesWrite: true}) : token;
    await addCommentReaction(reactionToken, {...decision.fields, commentId: decision.commentId, surface: decision.surface});
  } catch {
    console.log(JSON.stringify({event: "trigger.reaction_failed", comment_id: decision.commentId, surface: decision.surface}));
  }
  return Response.json({accepted: true, queued: true, trigger: message.trigger}, {status: 202});
}
