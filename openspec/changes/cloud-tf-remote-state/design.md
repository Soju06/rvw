## Context

See `proposal.md` for motivation. The infrastructure currently declares a local backend, while the release runner is ephemeral and A1 resources must be applied before the Worker resolves its concrete Queue and R2 bindings. Cloudflare's account API token can manage resources but is not an R2 S3 Access Key ID/Secret Access Key pair. Backend credentials are sensitive because Terraform can persist values passed as backend arguments under `.terraform`.

## Goals / Non-Goals

**Goals:** Coordinate shared Terraform runs with environment-isolated R2 state and native lockfiles; retain fully offline validation; keep App identity stable; and make the one-time bootstrap/security boundary explicit.

**Non-Goals:** Mint R2 credentials, create or mutate production resources during development, migrate an unknown pre-existing production state automatically, or replace the existing `RVW_CLOUD_DEPLOY` gate.

## Decisions

### Use a partial S3 backend with a native lockfile

`versions.tf` declares `backend "s3"` with only `use_lockfile = true` and raises the Terraform floor to 1.10. Operators supply bucket, environment-specific key, region `auto`, R2 endpoint, path-style mode, and the compatibility skip flags at `terraform init`. The Access Key ID and Secret Access Key are supplied as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, not as command arguments, so they are redacted by GitHub and omitted from backend command lines.

This uses Terraform's supported native S3 lock object and avoids a DynamoDB dependency that R2 cannot provide. Hardcoding the endpoint or one environment's key was rejected because it would couple source to an account and environment. Passing credentials via `-backend-config` was rejected because Terraform warns that backend values can be copied into `.terraform` and plan artifacts.

### Bootstrap the state bucket outside the state it stores

`cloud/infra/bootstrap/README.md` gives a one-time `wrangler r2 bucket create rvw-terraform-state` command and an owner-only dashboard procedure for an Object Read and Write R2 token scoped to that bucket. Keeping bootstrap imperative avoids a second Terraform state whose sole purpose is creating the first state store.

### Map dedicated release secrets into standard AWS environment names

The release workflow owns `R2_STATE_ACCESS_KEY_ID` and `R2_STATE_SECRET_ACCESS_KEY` as repository-secret names, then maps them to standard AWS SDK environment variables only for the Terraform step. The regular Cloudflare API token remains separately available to the provider for Queue and bucket resource operations.

### Keep the live spike on isolated local state

Until the owner provisions the R2 S3 token, live spike validation uses a disposable copy of the Terraform configuration whose backend is locally overridden under the dated evidence directory. This is explicitly measurement-only and is never committed or pushed; shared release behavior still uses R2.

## Risks / Trade-offs

- [R2 S3 compatibility differs from AWS] → Use Cloudflare's documented endpoint, path-style mode, checksum/identity validation skips, and Terraform 1.10+ native lockfile; validate the real backend after the owner provisions its dedicated token.
- [State bucket deletion or credential loss can prevent recovery] → Bootstrap once, keep the bucket outside the managed resource graph, and store the one-time secret values in repository secrets/password management.
- [Concurrent runs contend on the lock object] → Keep `use_lockfile = true`; the bucket-scoped token must permit read, write, and delete object operations for state and `.tflock` keys.
- [A release can start with no prior remote state] → The runbook requires owners to inspect/migrate any existing local state before the first shared apply; rollback restores workflow/code while retaining the state bucket.

## Migration Plan

1. Merge the code while `RVW_CLOUD_DEPLOY` remains disabled.
2. An owner creates `rvw-terraform-state`, mints a bucket-scoped R2 S3 token, and stores the two release secrets.
3. If production state already exists, initialize with the production backend configuration and migrate it deliberately; otherwise initialize the empty production key.
4. Enable the existing release gate only after backend initialization is verified.
5. Roll back by disabling `RVW_CLOUD_DEPLOY`; do not delete the state bucket or state objects during code rollback.
