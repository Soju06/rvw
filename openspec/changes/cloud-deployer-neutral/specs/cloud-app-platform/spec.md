## ADDED Requirements

### Requirement: Cloud assets are deployer-neutral
Cloud code and committed configuration MUST NOT contain deployer-specific identifiers; required deployer values MUST be provided by configuration and MUST fail closed when absent. Deployer-specific values MUST live outside this repository in private deployment configuration or CI variables and secrets.

#### Scenario: Repository neutrality is checked mechanically
- **WHEN** the deployer-neutrality guard scans tracked cloud, runtime, workflow, container, and documentation files
- **THEN** it exits non-zero with each offending file and line when a forbidden deployer identifier or account-shaped value is present
- **AND** it exits zero when the scoped tracked files are clean

#### Scenario: Required Worker configuration is absent
- **WHEN** a Worker request, queue delivery, or Durable Object alarm starts without a non-empty `CODEX_PROXY_HOST` or `GITHUB_APP_ID`
- **THEN** execution fails closed with a structured `config_missing` error naming the missing variable before any Sandbox or GitHub operation

## MODIFIED Requirements

### Requirement: Sandbox egress injects credentials at the proxy boundary
The Worker MUST export the SDK `ContainerProxy` integration, explicitly enable HTTPS interception on its Sandbox subclass, and configure `outboundByHost` at runtime for the required non-secret `CODEX_PROXY_HOST` without a committed fallback host. It MUST inject the `CODEX_API_KEY` Bearer credential only into requests for that configured host and emit a structured injection event that contains the hostname but no credential or authorization header value. The explicit environment passed when starting the sandbox review process MUST contain only a placeholder `CODEX_API_KEY` and the configured proxy `CODEX_BASE_URL`; inherited `RVW_CODEX_DEFAULT_BASE_URL` and `RVW_CODEX_SANDBOX` values MUST be unset before review commands run.

#### Scenario: Proxied Codex request is made
- **WHEN** a Sandbox request targets the configured proxy host
- **THEN** HTTPS interception invokes the Worker egress hook, the Worker supplies the Bearer secret and logs only the injection event and hostname, and the sandbox-visible credential remains a placeholder

#### Scenario: Different deployers configure different proxy hosts
- **WHEN** two Worker configurations select different non-empty proxy hosts
- **THEN** each configuration registers credential injection only for its selected host
- **AND** an unconfigured environment registers no outbound host

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
