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

### Requirement: Container application names are unique per environment
Each Wrangler environment MUST declare its own container application name for the `RvwSandbox` class as `rvw-sandbox-<environment>` (`rvw-sandbox-dev` for the default local development environment, `rvw-sandbox-spike`, and `rvw-sandbox-prod`). Two environments MUST NOT share a container application name, and any two environments MUST be deployable into the same Cloudflare account.

#### Scenario: Production is deployed while spike exists
- **WHEN** the `spike` container application already exists in the account and the `prod` environment is deployed
- **THEN** Wrangler creates or updates `rvw-sandbox-prod` bound to the production Durable Object namespace without renaming, replacing, or rejecting `rvw-sandbox-spike`

#### Scenario: Container names are checked offline
- **WHEN** the offline Python gate parses `cloud/wrangler.jsonc`
- **THEN** it asserts that the default, `spike`, and `prod` container application names are distinct and each ends with its environment name

### Requirement: Cloud source contains no credentials
No Cloudflare, GitHub, or Codex secret value, token, private key, or generated auth file MUST be committed. Runtime credentials MUST be represented only by secret bindings or documented operator commands.

#### Scenario: Repository is scanned for secrets
- **WHEN** source, configuration, image build inputs, and manifests are reviewed
- **THEN** no credential value is present and all secret references are placeholders or runtime names

### Requirement: Sandbox image ships a compatible reproducible GitHub CLI

The cloud Sandbox image MUST install an exact GitHub CLI release from the official
upstream release archive at `/usr/local/bin/gh`, MUST verify that archive against a
pinned SHA-256 and the checksum manifest from the same release, and MUST NOT install the
distribution-provided `gh` package. The image build MUST fail unless the installed
version is at least the declared minimum version that supports every pull-request field
used by rvw target resolution, including `headRefOid`.

#### Scenario: Sandbox image definition is inspected offline

- **WHEN** a maintainer inspects the cloud Dockerfile without network credentials
- **THEN** it declares exact GitHub CLI and minimum versions, omits `gh` from the
  distribution package list, and verifies the exact official release archive checksum

#### Scenario: Sandbox image is built

- **WHEN** the cloud Sandbox image build installs its declared GitHub CLI release
- **THEN** `/usr/local/bin/gh` reports that exact release and the build-time minimum
  version assertion succeeds

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

The Worker MUST export the SDK `ContainerProxy` integration, explicitly enable HTTPS interception on its Sandbox subclass, and configure `outboundByHost` at runtime for the required non-secret `CODEX_PROXY_HOST` without a committed fallback host. It MUST inject the `CODEX_API_KEY` Bearer credential only into requests for that configured host and emit a structured injection event that contains the hostname but no credential or authorization header value. The explicit environment passed when starting the sandbox review process MUST contain only a placeholder `CODEX_API_KEY` and the configured proxy `CODEX_BASE_URL`. Inherited endpoint and sandbox defaults MUST NOT override the adapter's explicit effective execution settings; the selected sandbox mode MUST be recorded in the Python process contract.

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
`.github/workflows/rvw-deploy.yml` MUST be a `workflow_call` workflow with typed inputs for `environment` (`spike` or `prod`), required `rvw_ref`, `account_id`, and `codex_proxy_host`, optional `worker_name` defaulting to `rvw-cloud-<environment>`, `github_app_id`, `job_deadline_minutes` defaulting to 90, and `manage_terraform` defaulting to true. It MUST declare the Cloudflare API token, Codex API key, GitHub App private key, webhook secret, admin token, and optional R2 state credentials as workflow secrets. It MUST checkout the requested tag, optionally initialize/apply Terraform, deploy Wrangler with CLI variable overlays, put the four Worker secrets, poll rollout readiness with a bounded wait for the new image digest, and require `/healthz` to report the selected environment. Before deploying, it MUST resolve the container application name from the selected environment's `containers` entry in `cloud/wrangler.jsonc`, MUST fail when that environment declares no container or a name not suffixed with the environment, and MUST scope the previous-digest capture and rollout wait to that resolved name rather than to another environment's entry. Job permissions MUST be minimal and all actions MUST be pinned by SHA.

#### Scenario: Workflow dry-run is deployer-neutral
- **WHEN** a caller invokes the workflow contract with placeholder inputs and no live credentials
- **THEN** its YAML parses and its Wrangler command uses CLI `--var` overlays without committed deployer-specific values

#### Scenario: Selected environment declares no container
- **WHEN** the workflow resolves the container application name for an environment whose Wrangler entry has no `containers`
- **THEN** it exits non-zero before `wrangler deploy` instead of waiting on the top-level local development application

### Requirement: Wrangler variables remain deployer-neutral
Committed Wrangler environments MUST NOT contain deployer-specific `CODEX_PROXY_HOST` or `GITHUB_APP_ID` values. Deploy commands MUST pass those values through CLI `--var` arguments, and CLI values MUST win over any generic committed defaults.

#### Scenario: CLI variable wins
- **WHEN** a Wrangler spike or prod dry-run supplies `CODEX_PROXY_HOST` and `GITHUB_APP_ID` with `--var`
- **THEN** the dry-run resolves those supplied values without requiring a committed deployer value

### Requirement: App review execution consumes the shared run contract

The App MUST invoke `rvw run` with the complete PR URL, captured webhook base and head SHAs, an explicit publication mode, and `--out /workspace/result`. Python MUST own repository binding, policy fallback, result classification, summary aggregation, and artifact discovery. The App MUST consume `process.json`, `summary.json`, and its manifest without parsing stdout for a verdict or run ID, copying from a guessed `/tmp/rvw` directory, or recounting discovery and adjudication results. The App MUST retain webhook validation, installation-token injection, Check Run API, queue and Durable Object lifecycle, Sandbox allocation/destruction, and R2 transport responsibilities.

#### Scenario: Webhook head is stale

- **WHEN** the current PR differs from the captured webhook anchors
- **THEN** Python returns `target_anchor_mismatch` and the App completes a neutral Check for the captured webhook head

### Requirement: App Check conclusions follow canonical execution status

The App MUST map a valid `pass` process contract with exit 0 and positive VALID coverage to Check conclusion `success`, `block` with exit 1 to `failure`, and `invalid` or `infra_failed` to `neutral`. Missing, malformed, inconsistent, or unsupported process or summary contracts MUST result in `neutral`. Zero VALID lanes MUST always produce `neutral`, including an otherwise valid-shaped PASS envelope. Check summary facts and common text MUST come from Python's summary; adapter-specific titles, links, and operational detail MUST remain separate presentation duties.

#### Scenario: Empty coverage is presented as PASS

- **WHEN** the process envelope says `pass` but summary records zero VALID lanes
- **THEN** the Check conclusion is `neutral` and never `success`

#### Scenario: Policy blocks after valid execution

- **WHEN** process status is `block`, exit code is 1, and the summary records valid execution
- **THEN** the Check concludes `failure` using the shared summary facts

### Requirement: Every App terminal path persists diagnostics before teardown

Normal completion, timeout, process start failure, process disappearance, and supersession MUST all attempt the same best-effort persistence of `run.log`, `process.json`, and `environment.txt`, plus available manifest artifacts, before destroying the Sandbox. Each attempted diagnostic MUST be independent so one failure does not prevent the others. The App MUST merge only SDK-observed supplements, including forced termination signal or reason, into Python's process envelope; it MUST NOT generate an independent incompatible process schema. A failure that prevents Python startup MUST use the shared Python initialization/finalization path where the Sandbox is reachable. Persistence or cleanup failures MUST preserve the original terminal classification and remain observable.

#### Scenario: Whole-job deadline expires

- **WHEN** the App deadline expires while review is active
- **THEN** it records timeout evidence, attempts all three diagnostics and available manifest artifacts, and only then destroys the Sandbox and completes a neutral Check

#### Scenario: Sandbox process cannot start

- **WHEN** starting the review process fails
- **THEN** the App attempts shared contract initialization/finalization and all diagnostic persistence before Sandbox destruction

#### Scenario: Newer head supersedes active review

- **WHEN** a newer job supersedes a running review
- **THEN** the older job attempts the same terminal diagnostic persistence before Sandbox destruction

### Requirement: App checks bootstrap presentation from the base revision

Before creating a check or sandbox, the App MUST read `.rvw/config.yaml` through the repository contents API with the captured base SHA and installation token. Missing config MUST select rvw/en defaults. Malformed config MUST select those bootstrap defaults and record `presentation_config_invalid` for the final check. Final Python-resolved presentation MUST supersede bootstrap presentation; check updates MUST support updating `name` to `short_name`. Check `external_id` MUST remain the job ID.

#### Scenario: PR changes display name

- **WHEN** base and head configuration differ
- **THEN** bootstrap check uses the base display name and short_name

#### Scenario: Malformed bootstrap configuration

- **WHEN** the contents response is malformed or schema-invalid
- **THEN** the initial check uses rvw/en and the final check reports presentation_config_invalid

### Requirement: App check chrome is localized and separates diagnostics

Worker Korean and English catalogs MUST have identical keys and format-compatible messages covering bootstrap, completion, deadline, superseded, exhausted queue, and missing-artifact paths. The check name MUST equal `short_name`; title MUST combine `display_name` with localized in-progress, complete, needs-changes, or incomplete state. A completed summary MUST consume Python's localized `markdown`, stating completion and CONFIRMED blocker plus CONFIRMED warning/suggestion counts with distinct uncovered-region disclosure when applicable. Neutral or failure summaries MUST use a localized human-reason sentence without job IDs, stderr dumps, or operational counters. Structured job ID, counts, lane validity, and artifact key MUST be retained in the check `text` collapsed section and artifacts. Python summary presentation MUST govern final check chrome.

#### Scenario: Completed check

- **WHEN** Python supplies locale ko with configured display and short names
- **THEN** the check uses those names and a Korean completion summary while structured details remain in text

#### Scenario: Deadline expires

- **WHEN** a job exceeds its deadline before Python completes
- **THEN** the check uses catalog-localized incomplete prose and preserves job and diagnostic details in text

### Requirement: App retains publication language outcomes

The App MUST consume nullable nonempty-string `publication_failure` and boolean `language_fallback_used` from Python process and summary contracts, defaulting absent legacy fields to null and false. A process with `infra_failed`, exit 3, and `publication_language_mismatch` MUST complete its check as neutral with catalog-localized human prose. The collapsed check `text` MUST retain the publication failure and fallback facts; those facts MUST NOT be hidden by a successful model review or reinterpreted as policy PASS.

#### Scenario: Review findings fail the language gate

- **WHEN** valid review evidence is retained but Python reports publication_language_mismatch with infra_failed and exit 3
- **THEN** the App finishes a neutral localized check, retains the failure in text, and sends no finding prose

#### Scenario: Explicit language fallback succeeds

- **WHEN** Python publishes through explicit fallback and reports language_fallback_used true
- **THEN** the App retains that fact in check text while preserving the canonical process conclusion
