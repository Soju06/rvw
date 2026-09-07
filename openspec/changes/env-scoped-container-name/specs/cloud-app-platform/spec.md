## ADDED Requirements

### Requirement: Container application names are unique per environment
Each Wrangler environment MUST declare its own container application name for the `RvwSandbox` class as `rvw-sandbox-<environment>` (`rvw-sandbox-dev` for the default local development environment, `rvw-sandbox-spike`, and `rvw-sandbox-prod`). Two environments MUST NOT share a container application name, and any two environments MUST be deployable into the same Cloudflare account.

#### Scenario: Production is deployed while spike exists
- **WHEN** the `spike` container application already exists in the account and the `prod` environment is deployed
- **THEN** Wrangler creates or updates `rvw-sandbox-prod` bound to the production Durable Object namespace without renaming, replacing, or rejecting `rvw-sandbox-spike`

#### Scenario: Container names are checked offline
- **WHEN** the offline Python gate parses `cloud/wrangler.jsonc`
- **THEN** it asserts that the default, `spike`, and `prod` container application names are distinct and each ends with its environment name

## MODIFIED Requirements

### Requirement: Reusable deployment workflow is explicit and bounded
`.github/workflows/rvw-deploy.yml` MUST be a `workflow_call` workflow with typed inputs for `environment` (`spike` or `prod`), required `rvw_ref`, `account_id`, and `codex_proxy_host`, optional `worker_name` defaulting to `rvw-cloud-<environment>`, `github_app_id`, `job_deadline_minutes` defaulting to 90, and `manage_terraform` defaulting to true. It MUST declare the Cloudflare API token, Codex API key, GitHub App private key, webhook secret, admin token, and optional R2 state credentials as workflow secrets. It MUST checkout the requested tag, optionally initialize/apply Terraform, deploy Wrangler with CLI variable overlays, put the four Worker secrets, poll rollout readiness with a bounded wait for the new image digest, and require `/healthz` to report the selected environment. Before deploying, it MUST resolve the container application name from the selected environment's `containers` entry in `cloud/wrangler.jsonc`, MUST fail when that environment declares no container or a name not suffixed with the environment, and MUST scope the previous-digest capture and rollout wait to that resolved name rather than to another environment's entry. Job permissions MUST be minimal and all actions MUST be pinned by SHA.

#### Scenario: Workflow dry-run is deployer-neutral
- **WHEN** a caller invokes the workflow contract with placeholder inputs and no live credentials
- **THEN** its YAML parses and its Wrangler command uses CLI `--var` overlays without committed deployer-specific values

#### Scenario: Selected environment declares no container
- **WHEN** the workflow resolves the container application name for an environment whose Wrangler entry has no `containers`
- **THEN** it exits non-zero before `wrangler deploy` instead of waiting on the top-level local development application
