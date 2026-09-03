## MODIFIED Requirements

### Requirement: Sandbox egress injects credentials at the proxy boundary

The Worker MUST export the SDK `ContainerProxy` integration, enable HTTPS interception on its Sandbox subclass, and configure host-specific egress handlers for the non-secret `CODEX_PROXY_HOST`, `api.github.com`, and `github.com`. The Codex handler MUST inject `CODEX_API_KEY` as a Bearer credential. The GitHub handlers MUST inject the current job's short-lived installation token, using Bearer authentication for API requests and Basic authentication with username `x-access-token` for git-over-HTTPS. Every injection MUST emit a structured event containing the hostname but no credential or authorization value. The Sandbox process environment MUST contain only a placeholder Codex credential and proxy URL and MUST NOT contain `GH_TOKEN` or `GITHUB_TOKEN`; a non-secret placeholder GitHub CLI configuration MAY be created solely to make `gh` issue requests whose credentials are replaced at the proxy boundary.

#### Scenario: Sandbox makes authenticated provider requests
- **WHEN** a review process calls the Codex proxy, GitHub API, or GitHub git-over-HTTPS endpoint
- **THEN** the matching egress handler supplies the real credential outside the Sandbox, logs only the hostname, and no real credential appears in the Sandbox environment

#### Scenario: Proxied Codex request is made
- **WHEN** a Sandbox request targets the configured proxy host
- **THEN** HTTPS interception invokes the Worker egress hook, the Worker supplies the Bearer secret and logs only the injection event and hostname, and the sandbox-visible credential remains a placeholder

### Requirement: Cloud release deployment is opt-in and ordered

The tag release workflow MUST include a `deploy-cloud` job after shared `gates`, gated by repository variable `vars.RVW_CLOUD_DEPLOY == 'true'`. Because the Worker binds to Terraform-managed Queue and R2 resources, Terraform apply MUST complete before the production Worker deploy begins. The gate MUST remain unchanged and no deployment may occur when it is not exactly `true`.

#### Scenario: Bound resources do not yet exist
- **WHEN** an opted-in cloud release provisions a new environment
- **THEN** Terraform creates the Queue, DLQ, and R2 bucket before Wrangler deploy resolves the production bindings

#### Scenario: Cloud deployment remains disabled
- **WHEN** the repository variable is not exactly `true`
- **THEN** the release workflow skips cloud deployment while other release jobs remain eligible

### Requirement: GitHub App contract is declared

The manifest MUST declare app name `rvw`, permissions `checks:write`, `pull_requests:write`, `contents:read`, and `metadata:read`, and events `pull_request`, `check_run`, `check_suite`, `installation`, and `installation_repositories`, with documented replaceable webhook and callback URL placeholders.

#### Scenario: A Check Run is re-requested
- **WHEN** GitHub delivers a `check_run.rerequested` event for an rvw Check Run associated with a pull request
- **THEN** the App contract permits the Worker to enqueue a review of the same pull-request head and update a new Check Run

#### Scenario: Manifest is used for registration
- **WHEN** an owner opens the documented manifest flow
- **THEN** GitHub presents exactly the declared permissions and events with replaceable webhook and callback URLs

## ADDED Requirements

### Requirement: GitHub webhook intake is authenticated and filtered

`POST /github/webhook` MUST verify `X-Hub-Signature-256` as an HMAC-SHA256 over the exact request bytes using `GITHUB_WEBHOOK_SECRET` and a constant-time comparison. Invalid or missing signatures MUST be rejected without Queue mutation. Valid `pull_request` events MUST enqueue only actions `opened`, `synchronize`, `reopened`, and `ready_for_review`; draft pull requests MUST be skipped except for `ready_for_review`. Valid `check_run.rerequested` events associated with a pull request MUST enqueue the same pull-request head. Every other valid event MUST return HTTP 202 without enqueueing.

#### Scenario: Signed supported event arrives
- **WHEN** GitHub sends a correctly signed supported, non-draft event
- **THEN** the Worker enqueues a serializable review message and returns HTTP 202 without running the review inline

#### Scenario: Signature is invalid
- **WHEN** a request has a missing or incorrect signature
- **THEN** the Worker returns HTTP 401 and does not enqueue a message

#### Scenario: Delivery is irrelevant
- **WHEN** a correctly signed event is unsupported or is a draft pull request not becoming ready
- **THEN** the Worker returns HTTP 202 and does not enqueue a message

### Requirement: Review job creation is idempotent and head-aware

Every message MUST use idempotency key `installation_id:repo_id:pr_number:head_sha`, and the Durable Object named by that key MUST be the authoritative job record. At-least-once deliveries for an in-flight or terminal key MUST NOT start another Sandbox process or Check Run. A newly delivered `check_run.rerequested` event MUST be the sole exception for a terminal same-head record: it MUST reset that record to `queued` and create a fresh review attempt, while replay of the same delivery ID remains a no-op. A `pull_request.synchronize` message carrying a distinct prior head MUST ask the prior head's job object to destroy its Sandbox and transition to `superseded` before the new job starts.

#### Scenario: GitHub redelivers one event
- **WHEN** duplicate Queue messages resolve to the same idempotency key
- **THEN** only the first message starts the job and subsequent messages acknowledge without duplicating work

#### Scenario: Pull request head changes
- **WHEN** a synchronize event supplies a prior head SHA different from the current head
- **THEN** the prior keyed job is superseded and its Sandbox is cancelled before the current keyed job starts

#### Scenario: Operator re-requests a terminal Check Run
- **WHEN** a new `check_run.rerequested` delivery targets the same terminal head key
- **THEN** the same Durable Object begins one fresh queued attempt, while replay of that delivery ID cannot start another attempt

### Requirement: Review job lifecycle is durable and deadline-bound

`RvwReviewJob` MUST persist transitions through `queued`, `provisioning`, `running`, `publishing`, and exactly one terminal state `completed`, `failed`, `timed_out`, or `superseded`. It MUST start the Sandbox review process in the background, persist its Sandbox/process identifiers, and schedule one alarm at 30-second intervals while work remains. Alarms MUST poll rather than wait for process completion and MUST reschedule healthy work. The hard deadline MUST be configured by `RVW_JOB_DEADLINE_MINUTES`, default to 90 minutes when absent or invalid, and transition overdue work to `timed_out` with a neutral Check Run after destroying the Sandbox. Observer activity MUST NOT kill a healthy job before that deadline.

#### Scenario: Durable Object is evicted during a review
- **WHEN** an alarm recreates the Durable Object while its Sandbox process remains active
- **THEN** persisted identifiers and timestamps allow polling to continue without restarting or cancelling the healthy process

#### Scenario: Review reaches its hard deadline
- **WHEN** the persisted deadline is reached before a parseable terminal result exists
- **THEN** the job destroys the Sandbox, transitions to `timed_out`, and concludes the Check Run as neutral with a timeout explanation

### Requirement: The review job owns Check Run semantics

Starting a job MUST create an rvw Check Run with status `in_progress`. A parseable `rvw auto` PASS result with exit code 0 MUST complete it as `success`; a parseable BLOCK result with exit code 1 MUST complete it as `failure`; infrastructure, transport, Sandbox, artifact, publication, or unparseable-result failures MUST complete it as `neutral` when a Check Run exists. Summaries MUST include available lane dispatched/valid counts, uncovered count, finding counts, and the artifact job identifier or configured artifact index link. The integration MUST NOT configure rvw as a required check by default, and existing rvw COMMENT publication remains owned by `rvw auto`.

#### Scenario: Policy blocks a pull request
- **WHEN** `rvw auto` exits 1 with a parseable BLOCK payload
- **THEN** the job completes normally and the Check Run conclusion is `failure`

#### Scenario: Review infrastructure fails
- **WHEN** the process crashes, transport fails, or its result cannot be parsed
- **THEN** the durable job records `failed` and the Check Run conclusion is `neutral` with the reason

### Requirement: GitHub App authentication is short-lived and scoped

The Worker MUST sign RS256 App JWTs from `GITHUB_APP_PRIVATE_KEY` and `GITHUB_APP_ID`, exchange them for installation access tokens, and cache each token in Durable Object storage only until five minutes before its reported expiry. Clone tokens MUST be scoped to the message repository where GitHub permits repository scoping. Source MUST never log JWTs, installation tokens, private keys, webhook secrets, or authorization values.

#### Scenario: Cached token remains usable
- **WHEN** a job requests an installation token more than five minutes before its expiry
- **THEN** the cached token is reused without another GitHub exchange

#### Scenario: Cached token nears expiry
- **WHEN** five minutes or less remain before expiry
- **THEN** the Worker exchanges a fresh App JWT for a new short-lived installation token

### Requirement: Review artifacts are persisted outside Durable Object state

For every terminally observed review, the Worker MUST copy each available `report.md`, `discover.json`, `merge.json`, `outcome.json`, and `run.log` file from `/workspace/result/` to R2 under `jobs/<job_id>/<artifact_name>`. HTTP job responses and Durable Object records MUST contain metadata only and MUST NOT inline artifact bodies.

#### Scenario: Review completes with artifacts
- **WHEN** the Sandbox process reaches a terminal state
- **THEN** available result files are streamed to R2 using deterministic job keys before Sandbox destruction

### Requirement: Queue failure handling and operator status are explicit

The Worker Queue consumer MUST resolve each message's keyed Durable Object and acknowledge successful or idempotent starts. Failed starts MUST be retried by Queue semantics up to the configured maximum, after which the message MUST move to `RVW_REVIEW_JOBS_DLQ`. `GET /jobs/:key` MUST be available in every environment, return metadata-only state from that keyed Durable Object, and require a constant-time-verified `Bearer RVW_ADMIN_TOKEN`. A0 spike routes MUST remain available only when `RVW_ENV == "spike"`.

#### Scenario: Operator inspects a job
- **WHEN** an operator supplies the correct bearer secret for an existing key
- **THEN** the Worker returns persisted job metadata without artifact contents or credentials

#### Scenario: Queue attempts are exhausted
- **WHEN** a start failure reaches the consumer retry limit
- **THEN** Cloudflare routes the message to the environment's declared dead-letter Queue

### Requirement: Rollout and cleanup account for independent Cloudflare resources

The runbook MUST require operators to verify that the container application reports the expected new image digest before trusting a Worker deployment. It MUST document that Worker deletion does not remove the container application or registry images and MUST provide explicit cleanup steps for all three resource classes. It MUST also document App registration, all required Worker secrets, Terraform-before-Worker deployment ordering, and Check Run re-request operation.

#### Scenario: Operator validates a rollout
- **WHEN** Wrangler reports a successful Worker deployment
- **THEN** the operator waits until the container application and healthy instances report the expected image digest before running production reviews
