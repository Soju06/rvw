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
| Variable | `RVW_JOB_DEADLINE_MINUTES` | Hard review deadline in minutes; defaults to 90. |
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

This directory is the Cloudflare Worker + Sandbox SDK execution plane.
The default Wrangler environment is local development (`RVW_ENV=dev`); `spike`
enables the bounded A0 lifecycle endpoints with `standard-2` and two instances;
`prod` uses the same `RvwSandbox` class with ten instances and keeps those
endpoints disabled (404). A1 accepts verified GitHub App webhooks, sends review
messages through an environment-specific Queue, observes each Sandbox process
with a Durable Object alarm, stores result artifacts in R2, and completes an rvw
Check Run. No dashboard, D1 database, or analytics are part of A1.

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
   bindings; `GITHUB_APP_ID`, `RVW_JOB_DEADLINE_MINUTES`, and
   `CODEX_PROXY_HOST` are non-secret vars supplied by the deployer.

### Observe and operate jobs

The hard job deadline is `RVW_JOB_DEADLINE_MINUTES` and defaults to 90. A healthy
process is polled every 30 seconds and is never killed because an HTTP observer
stopped waiting. Artifacts are stored under
`jobs/<installation_id:repo_id:pr_number:head_sha>/` as `report.md`,
`discover.json`, `merge.json`, `outcome.json`, and `run.log`; Worker responses
return keys and metadata only.

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
