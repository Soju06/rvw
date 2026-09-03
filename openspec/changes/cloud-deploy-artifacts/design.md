## Context

The current cloud scaffold has environment-specific resource literals and a
partial remote-state backend in the module, while the tag release workflow
provisions and deploys one production instance. Consumers need a stable module
source and reusable workflow that can be pinned together at a release tag.

## Goals / Non-Goals

**Goals:**

- Keep the module free of provider credentials and backend declarations.
- Expose every Queue, DLQ, R2, Durable Object, and Worker identifier needed by
  Wrangler bindings while allowing deployer-owned name overrides.
- Make the reusable workflow self-contained, explicit about secrets and
  permissions, and safe to call from a deployer repository.
- Ensure committed Wrangler config has no deployer-specific values and that CLI
  `--var` overlays are authoritative.
- Preserve offline validation and add deterministic dry-run/readiness contracts.

**Non-Goals:**

- Performing a live deployment, creating secrets, or mutating Cloudflare state.
- Managing a deployer repository's Terraform state when `manage_terraform` is
  false.
- Defining a shared provider or backend configuration in the published module.

## Decisions

- **Module contract:** use `name_prefix` plus optional queue and bucket override
  variables; derive generic defaults from the environment. `versions.tf` contains
  only Terraform/provider requirements. The deployer example owns the provider,
  R2 backend, and pinned module source.
- **Workflow contract:** require `environment`, `rvw_ref`, `account_id`, and
  `codex_proxy_host`; default only `worker_name`, `job_deadline_minutes`, and
  `manage_terraform`. Terraform backend values are supplied through workflow
  inputs and R2 secrets, never committed. Actions are SHA-pinned and job
  permissions are minimal.
- **Deployment order:** checkout the requested tag, optionally apply the module,
  deploy Wrangler with CLI vars, put four Worker secrets from stdin, then poll
  container metadata for the new digest and require `/healthz` to report the
  selected environment. The workflow records the deployed digest from Wrangler
  output and uses a bounded polling deadline.
- **Release notes:** the release job computes `${{ github.repository }}` and
  `${{ github.ref_name }}` in shell so notes include copyable workflow/module
  references without a hard-coded owner.
- **Wrangler overlays:** remove `CODEX_PROXY_HOST` and `GITHUB_APP_ID` from
  committed `vars`; retain generic environment vars and binding names. Every
  deploy command passes required values with `--var`.

## Risks / Trade-offs

- [Cloudflare rollout metadata differs across accounts] → Keep polling bounded,
  accept the documented A0 digest-reporting caveat, and fail before healthz if
  the exact digest is not observed.
- [A caller forgets to bump one pin] → Put the workflow `@tag` and module
  `?ref=tag` together in the example README and release notes.
- [Terraform output shape changes] → Treat output names as a compatibility
  contract and validate both module and example on every CI run.

## Migration Plan

Deployers copy the example layout, set private variables/secrets, and pin both
references to an rvw release tag. Existing private deployments can keep their
own Terraform state and call the workflow with `manage_terraform: false`; no
project-owned release deployment is migrated because it is removed.
