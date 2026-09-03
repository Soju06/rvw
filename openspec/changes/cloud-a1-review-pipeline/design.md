## Context

A0 established that a small review can take 24m33s and a realistic review can exceed 25 minutes. A request observer is therefore not a job supervisor. A1 stores review identity and progress in a Durable Object, lets the Sandbox process run independently, and uses DO alarms for short polling turns up to a configurable hard deadline that defaults to 90 minutes.

The target repository's base ref remains the rules source of truth. The Sandbox clones the exact head into a primary checkout and an adjacent verified checkout, fetches the recorded base SHA into both, and runs `python -m rvw.container_entrypoint auto --target <pr> --repo-dir <adjacent> --json` from the primary checkout with the explicit outer-Sandbox runtime policy. The entrypoint materializes the secret-free Codex client configuration before replacing itself with `rvw auto`; this preserves rvw's base-ref `.rvw/` loading and existing COMMENT publication path.

## Goals / Non-Goals

**Goals:** authenticated fast webhook intake, Queue decoupling, one idempotent durable job per head, alarm-driven observation, correct Check Run semantics, R2 artifact persistence, secret-free Sandbox environments, and safe resource rollout/cleanup.

**Non-Goals:** dashboard, D1, analytics, App registration or deployment, secret creation, required-check policy, rule editing, or changes to rvw's Python behavior.

## Sequence

```text
GitHub -> Worker /github/webhook: signed event bytes
Worker -> Worker: HMAC verify + filter + derive installation:repo:pr:head
Worker -> RVW_REVIEW_JOBS: send ReviewJobMessage
Worker --> GitHub: 202 Accepted

RVW_REVIEW_JOBS -> queue(): at-least-once message
queue() -> prior RvwReviewJob: supersede() [synchronize.before only]
prior RvwReviewJob -> prior Sandbox: kill/destroy [if active]
queue() -> current RvwReviewJob: start(message)
current RvwReviewJob -> GitHub API: App JWT -> installation token -> Check Run(in_progress)
current RvwReviewJob -> Sandbox: fresh getSandbox id + per-instance GitHub egress handlers
current RvwReviewJob -> Sandbox: clone head twice, fetch base, startProcess(rvw auto ...)
current RvwReviewJob -> DO storage: persist process id/deadline; setAlarm(+30s)

alarm() -> Sandbox: getProcess(process id)
Sandbox --> alarm(): running
alarm() -> DO storage: setAlarm(+30s)
... repeated without waiting or killing healthy work ...
Sandbox --> alarm(): terminal
alarm() -> R2: stream available /workspace/result artifacts
alarm() -> GitHub API: Check Run(completed, mapped conclusion + summary)
alarm() -> Sandbox: destroy
alarm() -> DO storage: terminal metadata
```

Webhook and Queue payloads contain metadata only. Artifact bodies never pass through HTTP responses or DO storage.

## Job identity and message

The canonical key is `installation_id:repo_id:pr_number:head_sha`. `job_id` equals that key. Messages also carry owner/name, base SHA, source event, optional previous head SHA, attempt, delivery ID, and enqueue timestamp. The same key always resolves through `RVW_REVIEW_JOB.getByName(key)`.

A synchronize event's documented `before` field identifies the previous head. The consumer derives its previous key and calls `supersede()` before starting the current key. Events without a prior-head field cannot safely guess a previous job and do not scan global state.

## Durable Object state machine

```text
                  duplicate start
                 +---------------+
                 |               v
queued -> provisioning -> running -> publishing -> completed
  |          |          |             |          (PASS or BLOCK)
  |          |          |             +--------> failed
  |          |          +----------------------> timed_out
  |          +---------------------------------> failed
  +--------------------------------------------> superseded
provisioning/running/publishing ----------------> superseded

terminal states: completed | failed | timed_out | superseded
terminal states reject ordinary later transitions; a new-delivery
check_run.rerequested is the sole terminal -> queued transition.
Replay of that delivery ID and all in-flight duplicates are no-ops.
```

Every transition is persisted before subsequent side effects and logged as structured JSON with job ID, from-state, to-state, timestamp, and non-secret reason where applicable. `running` persists Sandbox/process IDs and deadline. `publishing` persists artifact metadata after the available result set reaches R2. Before a forced terminal transition, the record persists pending Check-update and Sandbox-cleanup flags; terminal alarms retry either side effect after eviction or a transient failure.

## GitHub authentication and egress

The Worker imports the App PEM with Web Crypto and signs an RS256 JWT whose issued-at time is backdated 60 seconds and whose expiry is at most 10 minutes. It exchanges that JWT for an installation token, restricted to `repository_ids: [repo_id]`, and caches `{token, expires_at}` in the job DO until expiry minus five minutes.

The pinned Sandbox SDK supports class-level `outboundByHost` and named per-instance `outboundHandlers`. Codex uses the class-level configured proxy host. Each job assigns a named GitHub API handler and git handler to `api.github.com` and `github.com` with the short-lived token held in handler parameters outside the container. API requests receive `Authorization: Bearer`; git requests receive `Authorization: Basic base64("x-access-token:<token>")`. The clone URL is `https://x-access-token@github.com/<owner>/<repo>.git`, containing a username but no credential. A placeholder `hosts.yml` makes `gh` issue requests; the proxy overwrites its placeholder authorization. No `GH_TOKEN` or `GITHUB_TOKEN` is present in the process environment.

Offline coverage proves host selection and exact outbound header rewriting at the handler boundary. A live end-to-end clone is intentionally outside this no-secrets/no-deploy change; if production validation shows git does not preserve the injected header across its HTTPS authentication flow, the allowed fallback is a clone-command-only scoped token environment, never the Codex key and never the long-running rvw process environment.

## Check Run mapping

| Observation | DO terminal state | Check conclusion | Meaning |
|---|---|---|---|
| exit 0 + parseable `verdict: PASS` | `completed` | `success` | review passed policy |
| exit 1 + parseable `verdict: BLOCK` | `completed` | `failure` | review found a blocker |
| other exit, crash, missing process, malformed/mismatched JSON | `failed` | `neutral` | infrastructure or result failure |
| hard deadline reached | `timed_out` | `neutral` | review did not finish in configured time |
| newer head cancels job | `superseded` | `neutral` | result is obsolete |

Check API 5xx responses are retryable transport failures. Alarm handlers retain publishing state and reschedule so a healthy completed process is not rerun. If Check Run creation never succeeds after Queue retries, the message reaches the DLQ and no false repository conclusion is manufactured.

## Artifact layout and summary

R2 keys are `jobs/<job_id>/<name>` for `report.md`, `discover.json`, `merge.json`, `outcome.json`, and `run.log`. The DO stores only key, size, etag, and upload timestamp. Summary parsing is defensive: dispatched/valid/findings and the exact uncovered-hunk count come from discover coverage; outcome verdict values are counted when present. Missing or invalid required result JSON makes the Check Run neutral rather than guessing from the process exit alone. Without a configured artifact URL scheme, the summary reports the job ID.

## Failure matrix

| Failure | Detection | Durable action | Queue/Check behavior |
|---|---|---|---|
| webhook replay | same canonical key is delivered again | `start()` sees persisted non-queued/in-flight/terminal record and returns duplicate | Queue message is acknowledged; no second Sandbox or Check Run |
| duplicate Queue delivery | same key and message after at-least-once delivery | serialized DO RPC observes existing state | acknowledge as idempotent |
| Sandbox crash / missing process | alarm lookup fails or process disappears without valid result | persist artifacts/logs if available, transition `failed`, destroy | neutral Check Run with infrastructure reason |
| hard deadline | alarm time is at/after persisted deadline | kill/destroy, transition `timed_out` | neutral Check Run with timeout duration |
| GitHub 5xx during start | GitHub helper classifies 5xx as retryable | preserve resumable provisioning metadata | throw so Queue retries; exhausted messages go to DLQ |
| GitHub 5xx during terminal update | publishing alarm catches retryable response, or a forced-terminal record retains `checkUpdatePending` | remain `publishing` or keep terminal pending metadata, then reschedule | retry update without rerunning review |
| R2 put failure | binding throws during publishing | remain `publishing`, retain process/result metadata, reschedule | do not destroy until persistence/update succeeds or deadline policy resolves |
| superseding head | synchronize message includes different `before` SHA | prior job persists pending cleanup/update, transitions `superseded`, then kills and destroys with alarm retry | neutral prior Check Run; current job starts independently |

## Deployment and rollback

Terraform applies first because Queue and R2 names are concrete bindings in Wrangler. Wrangler then deploys the Worker and asynchronously rolls out its container application. Operators must inspect the application/instances and compare the reported image digest to the expected deploy digest before trusting reviews. Rollback uses Wrangler version rollback plus state-aware Terraform reversal. Full cleanup independently removes the Worker, container application, and obsolete registry images; Queue/R2 deletion remains Terraform state-managed and must account for retained artifacts.

## Open Questions

- Production validation should confirm an actual private-repository `git clone` follows the injected Basic header through every Git smart-HTTP request; this change can only prove the pinned SDK request-rewrite boundary offline without credentials or deployment.
- No public artifact URL is settled. Check summaries therefore identify `job_id`; a future operator-facing artifact index can add a details URL without changing R2 keys.
