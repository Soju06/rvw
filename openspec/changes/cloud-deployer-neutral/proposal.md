## Why

The self-hosted cloud scaffold currently commits identifiers and defaults for one deployer, which can misroute credentials and makes the open-source deployment path misleading. Required deployment identity must instead come from operator-owned configuration and fail closed when absent.

## What Changes

- **BREAKING** Remove committed defaults for the Codex proxy host and GitHub App ID; require both at Worker request and alarm entry points.
- Build Sandbox outbound credential injection from the configured proxy host at runtime and return structured `config_missing` failures when required values are absent or empty.
- Replace deployer-specific GitHub App manifest and documentation values with explicit placeholders and a complete deployer configuration contract.
- Add a tracked-file deployer-neutrality guard and run it in CI.
- Remove redundant Terraform credential plumbing while retaining environment-variable and secret-based authentication.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: Require deployer-neutral committed cloud assets, fail-closed required configuration, runtime-selected proxy injection, and a mechanical CI guard.

## Impact

This changes Worker startup/request behavior, Sandbox egress configuration, Wrangler vars and generated bindings, the GitHub App manifest, cloud and container CI documentation, Terraform/release workflow inputs, Worker tests, and repository CI gates. Deployers must supply `CODEX_PROXY_HOST` and `GITHUB_APP_ID` outside the repository before runtime traffic is accepted.
