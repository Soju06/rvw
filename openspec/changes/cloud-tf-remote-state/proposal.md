## Why

Cloud infrastructure state is currently local, so an opted-in release cannot safely coordinate Terraform runs across ephemeral CI runners. The already-registered `rvw-review` GitHub App also needs its stable numeric App ID declared consistently before live A1 validation.

## What Changes

- Store each environment's Terraform state and native S3 lockfile in one bootstrapped Cloudflare R2 bucket, using partial backend configuration and separately provisioned bucket-scoped R2 S3 credentials.
- Preserve credential-free offline Terraform initialization and validation, while making opted-in release deployment initialize the production R2 state before applying resources.
- Declare GitHub App ID `4813211` in every Wrangler environment and document the `rvw-review` installation URL.
- Document the one-time state-bucket bootstrap and the distinction between Cloudflare account API tokens and R2 S3 API credentials.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: Require an R2-backed, lockfile-enabled Terraform state contract, its one-time bootstrap, offline validation, and the registered App identity in every Worker environment.
- `release-automation`: Require opted-in cloud release deployment to initialize the environment-specific R2 state with owner-provisioned S3 credentials before Terraform apply.

## Impact

This changes `cloud/infra`, the Cloudflare runbook and Wrangler variables, the opt-in `deploy-cloud` workflow, OpenSpec deltas, and deterministic configuration tests. It adds no runtime secret values and does not alter production unless the existing `RVW_CLOUD_DEPLOY` gate is enabled by an owner.
