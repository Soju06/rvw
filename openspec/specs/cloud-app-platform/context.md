# Cloud app platform context

The A0 feasibility spike built a Cloudflare Sandbox Worker outside this repository. This scaffold ports that path into version control while preserving the owner decision that real credentials are injected by `outboundByHost` at egress and never placed in a sandbox process. Wrangler 4.128.0 confirms `image_build_context` is a supported container field; the cloud Dockerfile therefore uses repository-root context for source installation.

The implemented A1 architecture is webhook → Queue → Sandbox job → GitHub Check Runs API. The GitHub App permissions are checks write, pull requests write, contents read, and metadata read, with pull_request, check_run, and check_suite events. Check-run state starts at `in_progress` and resolves to `success`, `failure`, or `neutral`. Job messages carry a job identifier, installation/repository/PR identifiers, head SHA, source event, attempt, and timestamps. Artifacts are retained in R2 and job state is held by the review Durable Object; D1 metadata remains outside the implemented path.

Local change verification uses dry-runs, local Terraform validation, typechecking, and Docker builds without Cloudflare credentials. rvw publishes a Terraform module and reusable deployment workflow; deployers provision credentials and secrets in their own repositories.

The 2026-09-02 A0 rerun measured a roughly 3.6-second cold start and a roughly
24.5-minute small review on a `standard-2` instance. Inner
`codex --sandbox read-only` execution works on Cloudflare using Codex's bundled
bubblewrap, unlike the same probe in plain Docker, where namespace creation is
not permitted. These measurements support the Cloudflare execution path but do
not establish a production deadline for larger reviews.

Container application rollout is asynchronous: immediately after an image
update, a fresh sandbox can still run the previous image until application
instances refresh. Deployment readiness therefore requires instance/image
verification rather than assuming Worker deployment completion means the new
container is serving. Cleanup also has three independent scopes. Deleting the
Worker removes neither the container application nor Cloudflare registry
images; operators must delete the Worker, application, and obsolete image tags
separately.

The 2026-09-04 A1 live run against the v0.11.3 spike measured six seconds from
the accepted `pull_request.opened` webhook (09:34:08 UTC) to the in-progress
Check Run (09:34:14 UTC). Private clone authentication through the Worker
egress proxy passed: every observed `github.com` smart-HTTP request and the
single `api.github.com` GraphQL request returned HTTP 200. Two attempts still
ended at `publishing` after about 35 seconds from process start (44-45 seconds
from the operator action) and produced no R2 objects.

The artifact loss was independent of that early process exit. In pinned
`@cloudflare/sandbox` 0.12.9, `SandboxOptions.transport` is the control path
between the Sandbox Durable Object and its container and defaults to `http`
(`cloud/node_modules/@cloudflare/sandbox/dist/sandbox-BtaWcmmG.d.ts`, lines
789-807). `SANDBOX_TRANSPORT` is read from the Durable Object Worker environment,
not copied into the container process environment
(`cloud/node_modules/@cloudflare/sandbox/dist/sandbox-D0rNqxlr.js`, lines
7681-7697). The default route transport accepts automatic, UTF-8, and base64
`readFile` results, while raw `encoding: "none"` requires RPC; the route client
throws that exact error before requesting the file (same `.d.ts`, lines
3305-3322; same `.js`, lines 1867-1874). `readFileStream` is separately available
over the route transport through SSE (same `.d.ts`, lines 3323-3331). A1 has no
binary artifacts, so explicit UTF-8 reads are simpler and do not require a
transport configuration change.

The early exit was a roughly three-second process failure observed on the next
30-second alarm, not a short successful review. After clone completion, the
trace contains only the numeric target's initial `gh repo view` GraphQL request
and no PR-detail, diff, or Codex calls. The HTTP response was 200, but the lost
stderr means its application-level failure remains unproved; A1 now uses the
known full PR URL and bypasses that lookup. A second fast failure was provable:
the measured base revision had no `.rvw/policies/auto.yaml`, the image had no
external default policy, and rvw intentionally fails before its pipeline when
neither exists. The interim image supplied a versioned external fallback; the unified contract
replaces that copy with the package default after repository-base and deprecated
external-policy precedence. The checkouts, working directory,
`--repo-dir`, `CODEX_BASE_URL`, explicit `RVW_CODEX_SANDBOX`, and fetched base SHA
were all present and are not supported as causes by the source or live trace.

The 2026-09-04 v0.11.4 A1 rerun exposed a later image compatibility boundary. The
Sandbox image installed Debian's apt-provided GitHub CLI, reported as version 2.45.0,
and rvw target resolution failed after 4,467 ms when `gh pr view` rejected
`headRefOid` in `_PR_FIELDS` as an unknown JSON field. No lane dispatch or Codex
invocation occurred. Official GitHub CLI history identifies v2.18.0 as the release that
added `headRefOid`, and upstream v2.45.0 source contains the field, so the reported
version alone does not explain the observed binary behavior. The image contract now
removes that ambiguity: it installs the exact official v2.100.0 Linux amd64 archive at
`/usr/local/bin/gh`, authenticates it with the pinned SHA-256 and same-release checksum
manifest, and separately enforces the actual v2.18.0 compatibility floor during build.

## Unified App execution evidence (2026-09-05)

The `/tmp/rvw-surfaces-analysis.md` audit inspected committed v0.11.5 (`613201f`) code, not deployed image state. It found timeout persisted four stage artifacts but skipped `run.log`, `process.json`, and `environment.txt`, with the same diagnostic omission on start failure and supersession (`cloud/worker/src/review-job.ts:148–152,387–470,822–836`, baseline lines). Terminal handling now attempts one common best-effort persistence phase before Sandbox destruction, and SDK termination observations supplement the Python process schema rather than create a competing object.

App formerly supplied URL plus `GH_REPO` to compensate for unbound Python calls, installed fallback policy in an external-registry image path, parsed stdout for the run ID, copied artifacts out of `/tmp`, and recounted coverage/findings in TypeScript (`cloud/worker/src/sandbox-auth.ts:107–119`, `cloud/Dockerfile:46–47`, `cloud/worker/src/review-job-contract.ts:116–195`, baseline lines). It now passes webhook anchors and an explicit output directory to `run` and consumes Python process/summary/manifest files. Zero VALID lanes map to a neutral Check even if an envelope claims PASS. Webhook authentication, installation tokens and egress, queue/lifecycle, Check Run API, and R2 transport remain platform duties.
