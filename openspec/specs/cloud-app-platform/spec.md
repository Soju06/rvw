# cloud-app-platform

## Purpose

Defines the secret-free, reproducible Cloudflare Worker and Sandbox infrastructure
and the versioned deployment artifacts that consumers use to deploy their own
rvw instances. rvw publishes; it does not operate a Cloudflare account.

## Requirements

### Requirement: Cloud layout and environment contracts are explicit

The repository MUST contain the documented `cloud/` Worker, Sandbox image, driver, Terraform, and GitHub App manifest layout. Wrangler MUST define default local development plus `spike` and `prod` environments; `spike` MUST use Sandbox instance type `standard-2`, at most two instances, and class `RvwSandbox`, while `prod` MUST use the same class and at most ten instances.

#### Scenario: Configuration is inspected offline
- **WHEN** a maintainer runs Wrangler validation or dry-run for `spike` and `prod`
- **THEN** both environments resolve their declared bindings and limits without requiring Cloudflare credentials

### Requirement: Cloud source contains no credentials
No Cloudflare, GitHub, or Codex secret value, token, private key, or generated auth file MUST be committed. Runtime credentials MUST be represented only by secret bindings or documented operator commands.

#### Scenario: Repository is scanned for secrets
- **WHEN** source, configuration, image build inputs, and manifests are reviewed
- **THEN** no credential value is present and all secret references are placeholders or runtime names

### Requirement: Cloud assets are deployer-neutral
Cloud code and committed configuration MUST NOT contain deployer-specific identifiers; required deployer values MUST be provided by configuration and MUST fail closed when absent. Deployer-specific values MUST live outside this repository in private deployment configuration or CI variables and secrets.

#### Scenario: Repository neutrality is checked mechanically
- **WHEN** the deployer-neutrality guard scans tracked cloud, runtime, workflow, container, and documentation files
- **THEN** it exits non-zero with each offending file and line when a forbidden deployer identifier or account-shaped value is present
- **AND** it exits zero when the scoped tracked files are clean

#### Scenario: Required Worker configuration is absent
- **WHEN** a Worker request, queue delivery, or Durable Object alarm starts without a non-empty `CODEX_PROXY_HOST` or `GITHUB_APP_ID`
- **THEN** execution fails closed with a structured `config_missing` error naming the missing variable before any Sandbox or GitHub operation

### Requirement: Sandbox egress injects credentials at the proxy boundary
The Worker MUST export the SDK `ContainerProxy` integration, explicitly enable HTTPS interception on its Sandbox subclass, and configure `outboundByHost` at runtime for the required non-secret `CODEX_PROXY_HOST` without a committed fallback host. It MUST inject the `CODEX_API_KEY` Bearer credential only into requests for that configured host and emit a structured injection event that contains the hostname but no credential or authorization header value. The explicit environment passed when starting the sandbox review process MUST contain only a placeholder `CODEX_API_KEY` and the configured proxy `CODEX_BASE_URL`; inherited `RVW_CODEX_DEFAULT_BASE_URL` and `RVW_CODEX_SANDBOX` values MUST be unset before review commands run.

#### Scenario: Proxied Codex request is made
- **WHEN** a Sandbox request targets the configured proxy host
- **THEN** HTTPS interception invokes the Worker egress hook, the Worker supplies the Bearer secret and logs only the injection event and hostname, and the sandbox-visible credential remains a placeholder

#### Scenario: Different deployers configure different proxy hosts
- **WHEN** two Worker configurations select different non-empty proxy hosts
- **THEN** each configuration registers credential injection only for its selected host
- **AND** an unconfigured environment registers no outbound host

### Requirement: Spike controls fail closed by environment
The `/start`, `/status`, `/result`, and `/destroy` A0 endpoints MUST be available only when `RVW_ENV` is `spike`; any other environment MUST return HTTP 404 for those paths. `GET /healthz` MUST remain available and return the Worker version and environment. `/start` MUST accept a validated HTTPS GitHub repository URL and a 7-to-40-character lowercase hexadecimal commit SHA and MUST return HTTP 400 without creating a sandbox when either input is invalid. `/result` MUST read review artifacts from `/workspace/result/`.

#### Scenario: Production receives a spike request
- **WHEN** a request targets a spike path with `RVW_ENV=prod`
- **THEN** the Worker returns 404 without starting or mutating a Sandbox

#### Scenario: A maintainer measures an explicit repository commit
- **WHEN** the spike driver starts a review with a valid HTTPS GitHub repository URL and full or short commit SHA
- **THEN** the Worker runs that repository target and returns the artifacts written under `/workspace/result/`

#### Scenario: Invalid target input is rejected
- **WHEN** `/start` receives a missing or invalid repository URL or commit SHA
- **THEN** the Worker returns HTTP 400 without creating a sandbox

### Requirement: A0 driver reports observation outcomes truthfully
The spike driver MUST accept an observer deadline parameter that defaults to 25 minutes. It MUST exit non-zero when no completion marker is observed or when the review process exit code is non-zero. Its final summary MUST distinguish a review still running at the observer deadline from a transport failure, and it MUST state that reaching the observer deadline while still running is not evidence that the review itself failed.

#### Scenario: Healthy review outlives its observer
- **WHEN** status remains running when the configured observer deadline expires
- **THEN** the driver exits non-zero and reports an observer deadline outcome, not a review failure or transport failure

### Requirement: Offline verification gates are reproducible
CI MUST run the deployer-neutrality guard, cloud npm install, Worker unit tests, and TypeScript checks, Wrangler dry-runs for `spike` and `prod`, Terraform format/init-without-backend/validate, a cloud Docker build, and a Python packaging check proving distributions exclude `cloud/`. These gates MUST not require cloud credentials or required runtime-only Worker vars.

#### Scenario: Pull request runs cloud gates
- **WHEN** CI executes on a repository without Cloudflare secrets or deployer-specific Worker values
- **THEN** every cloud validation gate completes using local or dry-run behavior

### Requirement: GitHub App contract is declared
The manifest MUST declare app name `rvw`, permissions `checks:write`, `pull_requests:write`, `contents:read`, `metadata:read`, events `pull_request`, `check_run`, and `check_suite` (installation events are delivered to every App implicitly and MUST NOT be listed in `default_events`), and replaceable placeholders for the deployer's fork URL and Worker-host webhook and callback URLs.

#### Scenario: Manifest template is used for registration
- **WHEN** a deployer follows the documented manifest registration flow
- **THEN** the deployer replaces the fork and Worker-host placeholders before GitHub presents exactly the declared permissions and events

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
