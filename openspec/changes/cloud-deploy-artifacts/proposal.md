## Why

rvw is a self-hosted open-source tool that publishes software and deployment
assets; it does not operate a Cloudflare instance. The current release rail owns
an opt-in production deployment and the Terraform scaffold embeds state backend
concerns, which prevents independent deployers from consuming a versioned,
deployer-neutral module and workflow.

## What Changes

- **BREAKING** Remove the project-owned Cloudflare release deployment job and
  gate or instruction.
- Turn `cloud/infra` into a backend/provider-credential-free Terraform module
  with typed inputs, overridable resource names, and complete binding outputs.
- Add a complete placeholder deployer example, including an R2 backend example
  and a thin caller for the reusable workflow.
- Publish `.github/workflows/rvw-deploy.yml` as a `workflow_call` contract that
  checks out a pinned rvw tag, optionally manages Terraform, deploys Wrangler,
  sets secrets, and verifies bounded rollout readiness and `/healthz`.
- Make Wrangler deployment variables CLI overlays so deployers provide all
  account, proxy, and app identity values outside this repository.
- Add release notes containing the reusable workflow and Terraform module source
  lines for the release tag, derived from `github.repository`.
- Update cloud documentation, main specifications, and validation scenarios to
  describe “rvw publishes; you deploy”.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: define the versioned Terraform module, deployer example,
  reusable workflow inputs/secrets, rollout checks, and deployer-neutral config.
- `release-automation`: publish deployment artifacts and references without
  deploying any Cloudflare instance.

## Impact

Changes are confined to `cloud/infra`, `cloud/examples/deployer`, Wrangler
configuration and documentation, GitHub workflows, OpenSpec deltas, and cloud
validation. No Cloudflare account, credentials, secrets, or external registry
state are changed.
