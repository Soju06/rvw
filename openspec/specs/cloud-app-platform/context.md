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

## Container application naming (2026-09-07)

The first production deploy through the reusable workflow (deployer run
34094286509, job `deploy prod / deploy`, step `Deploy Worker`, 2026-09-07
07:14 UTC) built and pushed the image and then failed with:

```
✘ [ERROR] There is already an application with the name rvw-sandbox deployed that is associated with a different durable object namespace (<spike namespace id>). Either change the container name or delete the existing application first.
```

Cloudflare container applications are account-scoped by name and associated
with exactly one Durable Object namespace. `cloud/wrangler.jsonc` scoped the
Worker name (`rvw-cloud-spike`, `rvw-cloud-prod`), Queues, DLQs, and R2 buckets
per environment but named the Sandbox container `rvw-sandbox` in the default,
`spike`, and `prod` entries. The live `spike` deployment therefore owned the
name and `prod` could never deploy into the same account. The deploy workflow
repeated the assumption in a comment ("same across envs") and its rollout wait
fell back to the top-level entry when an environment declared no container.

The container application is now named `rvw-sandbox-<environment>`:
`rvw-sandbox-dev`, `rvw-sandbox-spike`, and `rvw-sandbox-prod`. Wrangler
4.128.0 offers no variable or templated container name and `--var` overlays only
`vars`; when `containers[].name` is omitted, its `validateContainerApp` config
validation derives `<worker name>-<class_name>` lowercased from the
configuration file's Worker name, appending `-<environment>` only for named
environments (`rvw-cloud-rvwsandbox` for the default entry,
`rvw-cloud-spike-rvwsandbox-spike` for spike), which would also be unique per
environment. Explicit literals were chosen because the workflow parses
`containers[0].name` from the committed configuration, the derived form ignores
a CLI `--name` override (the Worker name changes while the application name
does not), and it changes silently on a class rename.
The deploy workflow now resolves the selected environment's name before
`wrangler deploy`, rejects a missing or unsuffixed entry, and scopes both the
previous-digest capture and the rollout wait to that application so sibling
applications on the account are ignored. The Sandbox binding is by Durable
Object class (`RVW_SANDBOX` → `RvwSandbox`), and the Terraform module does not
model the container application, so Worker source and Terraform are unchanged.

Renaming is a create, not a rename, on the Cloudflare side. The next `spike`
deploy creates `rvw-sandbox-spike` bound to the existing spike Durable Object
namespace and leaves the old `rvw-sandbox` application (and its image tags)
running until the deployer deletes them with the documented
`wrangler containers delete` and `wrangler containers images delete` commands.
`prod` starts fresh as `rvw-sandbox-prod`. Rolling back to a release that still
uses the shared name only works while no other environment holds it. The
requirement is normative in `spec.md`; this section records the measured basis.

## Base-ref check presentation (2026-09-07)

The publication audit showed that check creation precedes sandbox provisioning, so Python-only configuration could not brand the first check. The Worker reads the four scalar `.rvw/config.yaml` fields from the captured base SHA using the installation token before creating the check. No YAML dependency exists in `cloud/package.json`; a minimal parser handles the supported scalar subset. Invalid bootstrap data selects rvw/en and records `presentation_config_invalid`; the authoritative Python snapshot can correct final branding through the update endpoint's name field. This does not grant PR-head configuration authority.

The owner chose short_name as the check name and display_name as the title prefix. Korean and English Worker catalogs cover pre-Python and terminal paths. Completed summaries consume the Python human sentence with confirmed finding counts and distinct uncovered-region disclosure. Neutral/failure summaries contain localized human reasons; job IDs, coverage/counts, artifact keys and operational evidence move into collapsed check text and retained artifacts. The check external_id remains the job ID. No deployment, Wrangler, Terraform, or container configuration changes accompany this presentation boundary.

## Publication locale enforcement (2026-09-07)

The Worker parser accepts the process and summary publication fields while remaining strict about field types and unknown fields. Legacy artifacts default publication_failure to null and language_fallback_used to false. A Python publication_language_mismatch remains infra_failed/exit 3 and yields a neutral localized check; structured failure/fallback facts appear in collapsed text. The Worker does not recount findings, rewrite model prose, or override the Python language decision.

## Explicit review deadline and job-cap coherence (2026-09-07)

The first production App review (bori#1744, rvw 0.13.0) passed no `--deadline`, so the CLI default of 600 s applied to every runtime execution; `environment.txt` and `process.json runtime.deadline` both recorded 600. Eight of fourteen runtime attempts ended at 600.06–600.16 s: `correctness` on all three discovery attempts, `hygiene` on two, `dynamic/goal-parity` once, and two of three initial adjudication replicas. Four sequential 600 s barriers were 97% of the 41-minute wall clock, and the 90-minute job cap was never approached, so the cap did not protect the review; the deadline did not fit the lanes.

Evidence for the value. 600 s was at the cap for `correctness` and `hygiene` in the App run and in four of five completed same-day local bori runs at 600 s (pr-1771, pr-1675 twice, pr-1769); the fifth (pr-1766) finished those lanes at 578 and 566 s, 96% and 94% of the cap. 1500 s recovered both lanes on bori #1692 but not on #1697, and the same-day local pr-1758 still hit 1500 s on both, so 1500 is a candidate, not a measured fix. 900 is the middle step: with the dead-lane redispatch skip, the no-retry path (discovery D, adjudication D) is 30 minutes, the no-adjudication-retry path with an expanded pass is 5D = 75 minutes, and the code worst case of 9D (discovery 3D for a lane that recovers with incomplete receipts, adjudication D + retry D, expanded 2D + retry 2D) is 135 minutes. The value is the Worker var `RVW_REVIEW_DEADLINE_SECONDS` so the owner can retune it without a release; the CLI ceiling of 1800 bounds it.

Coherence. Hitting the job cap yields a neutral check with nothing published, which is worse than the degraded-but-published result the review would otherwise reach, so `requiredConfig` requires `RVW_JOB_DEADLINE_MINUTES * 60 >= 5 * D + 600` (the 5D path plus ten minutes of provisioning, clone, merge, publish, and upload slack measured at roughly 5 s, 20 s, 2 s, and 27 s on #1744) and fails closed with `config_incoherent` / `job_deadline_below_review_budget` for every request and queue batch. At D = 900 the minimum is 85 minutes; the committed value is 120 for `dev`, `spike`, and `prod`. The reusable deploy workflow's `job_deadline_minutes` input defaults to 120 as well and overlays the committed value with `--var`; a deployer who raises D must raise that input too or the Worker refuses to serve. The 9D worst case is knowingly left above the cap.

The check `text` is the only place the operator can read the slowest phase without R2 access. Its `lanes` object now names both counts (`lane_hunk_receipts`, `uncovered_regions`), and it carries the Python `failed_lanes` and `wave_wall_seconds` facts verbatim. The Worker still renders none of the human sentences itself; the failed-lanes sentence comes from the Python catalogs through `summary.markdown`, so `i18n.ts` gains no keys.

The A0 spike review script passes the same explicit deadline so its measurements describe the production path, and a present but malformed `RVW_JOB_DEADLINE_MINUTES` now fails closed with `config_invalid` rather than silently becoming 90; only an absent var keeps the historical 90-minute default, which the coherence check still evaluates.
