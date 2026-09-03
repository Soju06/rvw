const SHA_PATTERN = /^[0-9a-f]{40}$/;
const SIGNATURE_PATTERN = /^sha256=([0-9a-f]{64})$/;
const PULL_REQUEST_ACTIONS = new Set([
  "opened",
  "synchronize",
  "reopened",
  "ready_for_review",
]);
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
}

export type WebhookDecision =
  | {kind: "ignore"}
  | {kind: "enqueue"; message: ReviewJobMessage};

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
  if (eventName !== "pull_request" && eventName !== "check_run") return {kind: "ignore"};
  const checkedDeliveryId = stringValue(deliveryId, "delivery ID");
  const payload = objectValue(value, "root");
  const action = stringValue(payload.action, "action");

  if (eventName === "pull_request") {
    if (!PULL_REQUEST_ACTIONS.has(action)) return {kind: "ignore"};
    const pullRequest = objectValue(payload.pull_request, "pull_request");
    if (pullRequest.draft === true && action !== "ready_for_review") return {kind: "ignore"};
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
    if (decision.kind === "enqueue") await env.RVW_REVIEW_JOBS.send(decision.message);
    return Response.json({accepted: true, queued: decision.kind === "enqueue"}, {status: 202});
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid webhook payload";
    return Response.json({error: message}, {status: 400});
  }
}
