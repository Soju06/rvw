## MODIFIED Requirements

### Requirement: Offline verification gates are reproducible
CI MUST run the deployer-neutrality guard, cloud npm install, Worker unit tests, and TypeScript checks, Wrangler dry-runs for `spike` and `prod`, Terraform format/init-without-backend/validate for both the published module and the deployer example, a cloud Docker build, and a Python packaging check proving distributions exclude `cloud/`. These gates MUST not require cloud credentials or required runtime-only Worker vars.

#### Scenario: Pull request runs cloud gates
- **WHEN** CI executes on a repository without Cloudflare secrets or deployer-specific Worker values
- **THEN** every cloud validation gate completes using local or dry-run behavior

## REMOVED Requirements

### Requirement: Cloud release deployment is opt-in and ordered
**Reason**: rvw publishes reusable deployment artifacts and does not operate a Cloudflare instance.
**Migration**: Deployers call the published reusable workflow from their own repository and consume the module pinned to the same release tag.

## ADDED Requirements

### Requirement: Published Terraform module has a stable deployer contract
The `cloud/infra` directory MUST be a reusable Terraform module with no provider credential configuration and no backend declaration. It MUST accept a required `account_id`, a validated `environment` of `spike` or `prod`, an optional `name_prefix` defaulting to `rvw`, and optional queue, dead-letter queue, and artifacts-bucket name overrides. It MUST output every queue/DLQ/bucket name and identifier required by the Worker bindings, including any Durable Object or Worker-relevant identifiers represented by the module.

#### Scenario: Module validates without credentials
- **WHEN** a consumer runs `terraform init -backend=false` and `terraform validate` in `cloud/infra`
- **THEN** validation succeeds without provider credentials or backend configuration

### Requirement: Deployer example is complete and pinned
`cloud/examples/deployer` MUST contain a provider-owned `main.tf`, placeholder `terraform.tfvars.example`, placeholder `backend.hcl.example`, a workflow caller example, and a README. The module source MUST pin an rvw release tag, and the example README MUST state that upgrades bump the module `ref` and reusable workflow `@tag` together.

#### Scenario: Example validates with dummy inputs
- **WHEN** a consumer supplies placeholder Terraform variables and runs init without a backend followed by validate
- **THEN** the example validates and contains no real account, host, credential, or app values

### Requirement: Reusable deployment workflow is explicit and bounded
`.github/workflows/rvw-deploy.yml` MUST be a `workflow_call` workflow with typed inputs for `environment` (`spike` or `prod`), required `rvw_ref`, `account_id`, and `codex_proxy_host`, optional `worker_name` defaulting to `rvw-cloud-<environment>`, `github_app_id`, `job_deadline_minutes` defaulting to 90, and `manage_terraform` defaulting to true. It MUST declare the Cloudflare API token, Codex API key, GitHub App private key, webhook secret, admin token, and optional R2 state credentials as workflow secrets. It MUST checkout the requested tag, optionally initialize/apply Terraform, deploy Wrangler with CLI variable overlays, put the four Worker secrets, poll rollout readiness with a bounded wait for the new image digest, and require `/healthz` to report the selected environment. Job permissions MUST be minimal and all actions MUST be pinned by SHA.

#### Scenario: Workflow dry-run is deployer-neutral
- **WHEN** a caller invokes the workflow contract with placeholder inputs and no live credentials
- **THEN** its YAML parses and its Wrangler command uses CLI `--var` overlays without committed deployer-specific values

### Requirement: Wrangler variables remain deployer-neutral
Committed Wrangler environments MUST NOT contain deployer-specific `CODEX_PROXY_HOST` or `GITHUB_APP_ID` values. Deploy commands MUST pass those values through CLI `--var` arguments, and CLI values MUST win over any generic committed defaults.

#### Scenario: CLI variable wins
- **WHEN** a Wrangler spike or prod dry-run supplies `CODEX_PROXY_HOST` and `GITHUB_APP_ID` with `--var`
- **THEN** the dry-run resolves those supplied values without requiring a committed deployer value
