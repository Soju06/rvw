# rvw Cloudflare deployment artifacts

rvw publishes deployment artifacts; you deploy. This repository does not operate
a Cloudflare account or instance. Consumers pin the Terraform module and
reusable workflow to one rvw release tag from their own deployment repository.

```hcl
module "rvw" {
  source = "github.com/<owner>/rvw//cloud/infra?ref=vX.Y.Z"
}
```

```yaml
uses: <owner>/rvw/.github/workflows/rvw-deploy.yml@vX.Y.Z
```

Use [`examples/deployer`](examples/deployer) as the minimal consumer layout.
Upgrade by bumping the module `ref` and workflow `@tag` together. Do not copy or
merge `wrangler.jsonc`; the reusable workflow checks out the selected tag and
passes deployer values as CLI overrides.

## Deployer configuration

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable | `CODEX_PROXY_HOST` | Sole hostname where the Worker injects the Codex API credential; required, and empty/unset fails closed. |
| Variable | `GITHUB_APP_ID` | Numeric GitHub App identifier; required, and empty/unset fails closed. |
| Variable | `RVW_REVIEW_DEADLINE_SECONDS` | Explicit per-runtime `--deadline` passed to `rvw run` (1 to 1800); committed default 900 for every environment. Missing or out-of-range values fail closed with `config_missing` or `config_invalid`. |
| Variable | `RVW_JOB_DEADLINE_MINUTES` | Hard job deadline in minutes; committed default 120 for every environment, 90 when the var is absent, and a malformed value fails closed with `config_invalid`. Must satisfy `minutes * 60 >= 5 * RVW_REVIEW_DEADLINE_SECONDS + 600` or every request fails closed with `config_incoherent` (`job_deadline_below_review_budget`). The reusable deploy workflow overlays this var from its `job_deadline_minutes` input (default 120, matching the committed value); raise it whenever you raise the review deadline. |
| Variable | `RVW_CODEX_MODEL` | Optional Codex model passed as `--model` to every review runtime (discovery and adjudication) of every App job and spike run. Absent means the packaged CLI default `gpt-6-astra`; a present but empty value fails closed with `config_invalid`. The effective value is recorded in `process.json` `runtime.model`, `environment.txt`, `usage.json`, and the check `text` facts. Not set in the committed Wrangler config; set it for one deployment through the reusable deploy workflow's `codex_model` input and deploy again without it to clear. Never set it through the Workers settings API (that rewrites the bindings set and detaches the container application). |
| Variable | `RVW_CODEX_REASONING_EFFORT` | Optional Codex reasoning effort passed as `--reasoning-effort` to every review runtime. Absent means the packaged CLI default `high`; the value must be exactly one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `persistent` (lowercase) or every request fails closed with `config_invalid`. The effective value is recorded in `process.json` `runtime.reasoning_effort`, `environment.txt`, `usage.json`, and the check `text` facts. Not set in the committed Wrangler config; set it for one deployment through the reusable deploy workflow's `codex_reasoning_effort` input and deploy again without it to clear. Never set it through the Workers settings API. |
| Secret | `CODEX_API_KEY` | Required upstream Codex credential, injected only at the configured proxy boundary. |
| Secret | `GITHUB_APP_PRIVATE_KEY` | Required GitHub App private key used to mint installation tokens. |
| Secret | `GITHUB_WEBHOOK_SECRET` | Required secret used to verify GitHub webhook signatures. |
| Secret | `RVW_ADMIN_TOKEN` | Required bearer token for operator job-status endpoints. |
| Terraform variable | `account_id` | Required Cloudflare account identifier for resource provisioning. |
| Terraform variable | `environment` | Required resource suffix (`dev`, `spike`, or `prod`). |
| State backend credential | `R2_STATE_ACCESS_KEY_ID` → `AWS_ACCESS_KEY_ID` | Required access-key ID for the remote R2 Terraform state bucket. |
| State backend credential | `R2_STATE_SECRET_ACCESS_KEY` → `AWS_SECRET_ACCESS_KEY` | Required secret access key for the remote R2 Terraform state bucket. |

Terraform also reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from
CI/environment configuration. Never commit these values.

For deployment, pass the required non-secret values from private CI variables
with Wrangler `--var CODEX_PROXY_HOST:<host> --var GITHUB_APP_ID:<id>` overrides.
The reusable workflow maps caller inputs to those Worker binding names.

### Codex model and reasoning effort overrides

Every review runtime runs the packaged default `gpt-6-astra` at reasoning effort `max`
unless a deployer opts in to an override. Precedence per field is explicit CLI option >
environment variable > packaged default, on both the CLI and the App path: the Worker
appends `--model` / `--reasoning-effort` to the `rvw run` argv only when
`RVW_CODEX_MODEL` / `RVW_CODEX_REASONING_EFFORT` are set, so an unset var leaves the
container's own resolution untouched. The effective values travel into every artifact
(`process.json` `runtime.model` and `runtime.reasoning_effort`, `environment.txt`
`model=` / `reasoning_effort=`, `usage.json`, and the canonical `command`) and the
check `text` facts carry `runtime: {model, reasoning_effort}` read back from
`process.json` (`null` when `process.json` is missing or unparseable; per-field `null`
for envelopes written by an image that predates the keys). Set both vars with Wrangler
`--var RVW_CODEX_MODEL:<model> --var RVW_CODEX_REASONING_EFFORT:<effort>` for an A/B
cell and drop them to return to the default; a malformed value fails every request
closed with `config_invalid` naming the variable.

### Sandbox egress

HTTP(S) egress from a review sandbox is allowlisted for the whole run to the configured
Codex proxy host, `api.github.com`, and `github.com` (`setAllowedHosts` beside the
credential-injecting per-host handlers); every other host is answered by the Worker proxy
with HTTP 520 and no credential. Non-HTTP protocols are not intercepted. Inside the
container, model-driven tool commands additionally run behind the image's review-phase
shims (see `docs/container-image.md`), so `git fetch`, `gh`, `curl`, and `wget` are refused
while the rvw CLI's own clone, target resolution, and publication keep their access.
`github.com` stays reachable after the clone completes because the CLI clones inside the
review process; the gap and the follow-up (clone before `startProcess` behind `--repo-dir`,
then `denyHost("github.com")`) are recorded in the cloud-app-platform context.

This directory is the Cloudflare Worker + Sandbox SDK execution plane.
The default Wrangler environment is local development (`RVW_ENV=dev`); `spike`
enables the bounded A0 lifecycle endpoints with `standard-2` and two instances;
`prod` uses the same `RvwSandbox` class with ten instances and keeps those
endpoints disabled (404). A1 accepts verified GitHub App webhooks, sends review
messages through an environment-specific Queue, observes each Sandbox process
with a Durable Object alarm, stores result artifacts in R2, and completes an rvw
Check Run. No dashboard, D1 database, or analytics are part of A1.

The container application is named per environment (`rvw-sandbox-dev`,
`rvw-sandbox-spike`, `rvw-sandbox-prod`) because Cloudflare container
applications are account-scoped by name and bound to one Durable Object
namespace, so spike and prod can only coexist with distinct names. Migrating an
existing environment to its per-environment name creates a new container
application on the next deploy; the deployer must delete the previous
application with `npx wrangler containers delete <container-application-id>`.

## Offline checks

```bash
npm ci
npx tsc --noEmit
npm test
npx wrangler deploy --dry-run --outdir dist --env spike --var CODEX_PROXY_HOST:proxy.example --var GITHUB_APP_ID:1
npx wrangler deploy --dry-run --outdir dist --env prod --var CODEX_PROXY_HOST:proxy.example --var GITHUB_APP_ID:1
(cd infra && terraform fmt -check && terraform init -backend=false && terraform validate)
(cd examples/deployer && terraform fmt -check && terraform init -backend=false && terraform validate)
docker build -f cloud/Dockerfile .
```

Wrangler 4.128.0's schema supports `containers[].image_build_context`; this config
sets it to `..` so Wrangler builds from the repository root and installs rvw from
checked-out source. Consequently the equivalent local Docker command uses
`-f cloud/Dockerfile .`; `docker build cloud/` alone cannot access the parent
Python source and is not a valid source build context.

## A0 driver

After an owner deploys the `spike` environment, run

```bash
scripts/drive-spike.sh https://<worker-host> https://github.com/<owner>/<repo> <target-sha> [deadline-seconds]
```

The optional observer deadline defaults to 1,500 seconds (25 minutes). The
driver polls until it sees the process completion marker or the deadline,
fetches available result artifacts, prints a final outcome summary, and always
attempts `/destroy` via an EXIT trap.

`POST /start` keeps `repo` and `target` as query parameters and accepts an optional
JSON body carrying per-run Codex overrides for an A/B cell:

```bash
curl --fail-with-body --request POST \
  --header 'Content-Type: application/json' \
  --data '{"model":"gpt-6-astra","reasoning_effort":"high"}' \
  "https://<worker-host>/start?repo=https://github.com/<owner>/<repo>&target=<target-sha>"
```

Both keys are optional; a body override wins over the Worker's `RVW_CODEX_MODEL` /
`RVW_CODEX_REASONING_EFFORT` vars for that run, and an absent field falls back to the
var and then to the packaged CLI default. `model` must be a non-empty string and
`reasoning_effort` must be one of the nine effort values listed in the configuration
table. Malformed JSON, an unknown key, an empty model, or an off-enum effort is answered
with HTTP 400 and no sandbox is created, so a typo cannot silently run the default cell.
The 202 response echoes the effective `model` and `reasoning_effort` (`null` when the
CLI default applies), and the run's `process.json` records the values the container
actually used. The driver forwards its own environment: when `RVW_CODEX_MODEL` or
`RVW_CODEX_REASONING_EFFORT` is set in the shell that runs `drive-spike.sh`, it sends
them as that JSON body (built with `jq -n --arg`) and saves it as
`spike-evidence/run/start-body.json`; otherwise the request is unchanged.

```bash
RVW_CODEX_MODEL=gpt-6-astra RVW_CODEX_REASONING_EFFORT=high \
  scripts/drive-spike.sh https://<worker-host> https://github.com/<owner>/<repo> <target-sha>
```

Exit status `0` means the completion marker reported review exit `0`. Usage
errors exit `2`; transport, API, or malformed-response failures exit `3`; a
review still running at the observer deadline exits `4`; a terminal process
without a valid completion marker exits `5`; and a completed review with a
non-zero process exit exits `6`. A healthy job reaching the observer deadline
is an observer failure, not evidence that the review itself failed. This bounded
A0 driver still destroys its sandbox on exit, so production-sized work needs
the planned durable A1 job lifecycle.

## Rollout readiness and cleanup

Container application rollout is asynchronous. A Worker deployment can finish
before existing application instances refresh, and a newly requested sandbox
can briefly run the previous image. Record the digest produced for the deploy,
inspect the container application and every serving instance with the Wrangler
container inspection commands, and do not trust the rollout until the
application reports that exact digest and the refreshed instances are healthy:

```bash
npx wrangler containers list --json
npx wrangler containers info <container-application-id> --json
npx wrangler containers instances <container-application-id> --json
```

A successful Worker deploy alone is not readiness.

Cloudflare retains three independently managed resource classes. Removing a
Worker does not remove its container application or registry images. For a full
spike cleanup, inspect targets first and then remove all three explicitly:

```bash
npx wrangler delete --env spike
npx wrangler containers list
npx wrangler containers delete <container-application-id>
npx wrangler containers images list
npx wrangler containers images delete <image>:<tag>
```

Repeat the image deletion command for every spike tag that is no longer needed.
These commands require Cloudflare credentials and are operator actions, not
offline checks. Queue, DLQ, and R2 lifecycle is separately managed through
Terraform state; inspect and retain/download R2 artifacts before any approved
Terraform destroy.

## A1 GitHub App review runbook

### Provision and deploy ordering

Each Wrangler environment binds concrete names:

- `rvw-review-jobs-<environment>` and `rvw-review-jobs-dlq-<environment>`
- `rvw-artifacts-<environment>`
- the `RvwReviewJob` Durable Object namespace

Terraform must be applied for the selected environment before deploying its
Worker so the Queue, DLQ, and R2 bucket exist when Wrangler resolves bindings.
The reusable workflow performs that ordering when `manage_terraform` is true;
consumers may manage Terraform themselves and set it false.

### Register the GitHub App

1. Replace the `<your-org>/<your-fork>` and `<worker-host>` placeholders in
   `cloud/github-app.manifest.json`. The webhook URL must be
   `https://<worker-host>/github/webhook`; the callback remains a registration
   placeholder because A1 has no user OAuth flow.
2. Open GitHub's App manifest creation flow and submit the template. Confirm the
   requested permissions are Checks write, Pull requests write, Contents read,
   and Metadata read, and confirm `pull_request` plus `check_run` are among the
   subscribed events.
3. Record the generated numeric App ID in the deployer's private
   `GITHUB_APP_ID` Wrangler override, download the App private key once, create a
   webhook secret, and install the App on the intended repositories.
4. Configure the four Worker secrets interactively for each deployed environment:

   ```bash
   npx wrangler secret put GITHUB_APP_PRIVATE_KEY --env spike
   npx wrangler secret put GITHUB_WEBHOOK_SECRET --env spike
   npx wrangler secret put CODEX_API_KEY --env spike
   npx wrangler secret put RVW_ADMIN_TOKEN --env spike
   ```

   Repeat with `--env prod` for production. Never place values in JSON, shell
   history, logs, `.dev.vars`, or committed files. `GITHUB_APP_PRIVATE_KEY`,
   `GITHUB_WEBHOOK_SECRET`, `CODEX_API_KEY`, and `RVW_ADMIN_TOKEN` are secret
   bindings; `GITHUB_APP_ID`, `RVW_JOB_DEADLINE_MINUTES`, `RVW_REVIEW_DEADLINE_SECONDS`,
   `CODEX_PROXY_HOST`, and the optional `RVW_CODEX_MODEL` / `RVW_CODEX_REASONING_EFFORT`
   are non-secret vars supplied by the deployer.

### Publication identity and permissions

The Worker passes `RVW_GITHUB_LOGIN=<app-slug>[bot]` into the review process (read from
the check-run creation response, or from the existing check run when a job re-enters) so
Python can recognise, reuse, and resolve its own inline review threads and dismiss its own
earlier REQUEST_CHANGES reviews. Reading and resolving review threads and dismissing
reviews use the `pull_requests: write` permission the App manifest already declares; no
new permission is needed. The Worker never chooses the review event: the consuming
repository's `.rvw/policies/auto.yaml` at the base ref does, and the check `text` carries
the resulting `publish` facts and any `publication_skipped` reason verbatim. The App argv
uses `--publish github-review`; the earlier `github-comment` spelling remains accepted by
the container for one release. Because a container rollout is asynchronous, a sandbox can
briefly run the previous image after a Worker deploy; such a job ends as a neutral check.

### Observe and operate jobs

Each runtime execution inside the review receives the explicit `--deadline`
`RVW_REVIEW_DEADLINE_SECONDS` (committed default 900). The hard job deadline is
`RVW_JOB_DEADLINE_MINUTES` (committed default 120) and the Worker refuses to serve
any request unless `RVW_JOB_DEADLINE_MINUTES * 60 >= 5 * RVW_REVIEW_DEADLINE_SECONDS + 600`:
five runtime waves on the no-adjudication-retry path (discovery initial and retry,
adjudication initial, and the doubled expanded pass) plus ten minutes of provisioning,
clone, publish, and upload slack. With 900 seconds the minimum is 85 minutes; the code
worst case of nine waves (135 minutes at 900 seconds) is deliberately not covered and
ends as a neutral check. Deploys through the reusable workflow overlay
`RVW_JOB_DEADLINE_MINUTES` from the `job_deadline_minutes` input, whose default of 120
matches the committed value; raise both together with the review deadline. A healthy
process is polled every 30 seconds and is never killed because an HTTP observer
stopped waiting. Artifacts are stored under
`jobs/<installation_id:repo_id:pr_number:head_sha>/` as `report.md`,
`discover.json`, `merge.json`, `outcome.json`, `run.log`, `process.json`, and
`environment.txt`; Worker responses return keys and metadata only. When a
process ends, the Worker saves SDK-captured stdout/stderr, process exit facts,
and the available redacted environment snapshot before interpreting result
artifacts. A missing-result Check Run includes the exit code, duration, and a
credential-filtered tail of approximately 20 stderr lines.

An operator can inspect metadata in any environment with:

```bash
curl --fail-with-body \
  --header "Authorization: Bearer <RVW_ADMIN_TOKEN>" \
  "https://<worker-host>/jobs/<installation_id:repo_id:pr_number:head_sha>"
```

To re-run a completed review at the same head, open the rvw Check Run in GitHub
and choose **Re-run**. GitHub sends `check_run.rerequested`; a new delivery ID
resets the same head-keyed Durable Object to a fresh queued attempt. Replayed
deliveries and requests received while that key is already in flight are no-ops.

The Sandbox environment contains only a placeholder `CODEX_API_KEY` and the
Codex proxy URL. GitHub API and git clone credentials are short-lived,
repository-scoped installation tokens attached by the Worker egress handlers;
neither `GH_TOKEN` nor `GITHUB_TOKEN` is passed to the review process.

All current A1 artifacts are text and are read explicitly as UTF-8. On pinned
`@cloudflare/sandbox` 0.12.9, the default HTTP transport supports UTF-8 and
base64 `readFile` results; only raw `encoding: "none"` requires RPC.
`SANDBOX_TRANSPORT` configures the Sandbox Durable Object's Worker environment,
not the review process environment, and `getSandbox(..., {transport: "rpc"})`
is the explicit per-sandbox alternative. A route-compatible `readFileStream`
API also exists for future binary artifacts. A1 does not enable RPC because it
has no binary artifacts.

The image installs a versioned fallback auto policy at
`/root/.hermes/review/policies/auto.yaml`. rvw still checks the target base
revision for `.rvw/policies/auto.yaml` first, so repository policy takes
precedence. The A1 command uses the full pull-request URL from the webhook
message and supplies its non-secret repository identity to `gh`, avoiding a
redundant `gh repo view` lookup and remote inference before PR resolution.

The pinned SDK's outbound-request boundary and the exact Basic authorization
rewrite are covered offline. Before trusting the first production rollout,
confirm a private-repository clone completes through the handler. If that live
check disproves git smart-HTTP compatibility, limit the documented fallback to
a scoped installation token in the clone command's environment only; never pass
it to the long-running `rvw auto` process and never substitute the Codex key.

## Bootstrap and one-time manual steps

Terraform state has a separate chicken-and-egg bootstrap. Follow
[`infra/bootstrap/README.md`](infra/bootstrap/README.md) to create
`rvw-terraform-state` once and provision the owner-managed repository secrets
`R2_STATE_ACCESS_KEY_ID` and `R2_STATE_SECRET_ACCESS_KEY`. These are R2 S3
credentials and are distinct from the Cloudflare account API token below.

Bootstrap Cloudflare API token permission checklist (owner performs once; store
the resulting values as GitHub repository secrets):

- [ ] Workers Scripts: Edit
- [ ] Workers Containers / Registry image: Write
- [ ] Durable Objects: Edit (as needed)
- [ ] Queues: Edit (as needed)
- [ ] R2: Edit (as needed)
- [ ] Account Settings: Read
- [ ] Save token as `CLOUDFLARE_API_TOKEN`
- [ ] Save account identifier as `CLOUDFLARE_ACCOUNT_ID`

The App registration and all four per-environment Worker secrets are detailed in
the A1 runbook above. The Worker injects the Codex secret only at
`CODEX_PROXY_HOST`; Sandbox processes receive a placeholder value.
