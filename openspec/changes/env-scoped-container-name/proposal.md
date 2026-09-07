## Why

The first production deploy through the reusable workflow failed after the
image build and push succeeded: Wrangler reported that an application named
`rvw-sandbox` already existed and was associated with a different Durable
Object namespace. Cloudflare container applications are account-scoped by name
and bound to exactly one Durable Object namespace, but `cloud/wrangler.jsonc`
named the Sandbox container `rvw-sandbox` in the default, `spike`, and `prod`
environments. While `spike` holds the name, `prod` can never deploy into the
same account, and the deploy workflow encoded the same wrong assumption in its
rollout wait.

## What Changes

- **BREAKING** Name the container application per environment:
  `rvw-sandbox-dev` (default local development), `rvw-sandbox-spike`, and
  `rvw-sandbox-prod`, keeping the `RvwSandbox` class, image, build context,
  instance types, and instance limits unchanged. Cloudflare treats this as a
  create, not a rename: an environment already deployed under `rvw-sandbox`
  gets a new application on its next deploy and the deployer must delete the
  old one.
- Make the reusable deploy workflow resolve the selected environment's container
  application name from `wrangler.jsonc` before deploying, fail closed when that
  environment declares no container or a name not scoped to it, and reuse the
  resolved name for the rollout wait instead of assuming one shared name.
- Add an offline Python regression test that every environment declares a
  distinct, environment-suffixed container application name and that the
  workflow resolver selects the environment-specific entry without falling
  back to the top-level entry.
- Document that the application is named per environment and that migrating an
  existing environment creates a new application whose predecessor the deployer
  must delete.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: Require unique per-environment container application
  names and an environment-scoped rollout wait in the reusable deploy workflow.

## Impact

`cloud/wrangler.jsonc`, `.github/workflows/rvw-deploy.yml`,
`tests/test_cloud_remote_state.py`, `cloud/README.md`, and the
`cloud-app-platform` specification and context change. Worker source binds the
Sandbox by Durable Object class (`RVW_SANDBOX` → `RvwSandbox`), not by
application name, and the Terraform module does not reference the container
application, so neither changes. For existing deployments, the next deploy of an
environment that already runs under `rvw-sandbox` creates a new container
application (`rvw-sandbox-spike` for spike) and orphans the old one, which the
deployer must delete explicitly.
