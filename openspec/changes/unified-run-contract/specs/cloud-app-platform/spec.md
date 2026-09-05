## MODIFIED Requirements

### Requirement: Sandbox egress injects credentials at the proxy boundary

The Worker MUST export the SDK `ContainerProxy` integration, explicitly enable HTTPS interception on its Sandbox subclass, and configure `outboundByHost` at runtime for the required non-secret `CODEX_PROXY_HOST` without a committed fallback host. It MUST inject the `CODEX_API_KEY` Bearer credential only into requests for that configured host and emit a structured injection event that contains the hostname but no credential or authorization header value. The explicit environment passed when starting the sandbox review process MUST contain only a placeholder `CODEX_API_KEY` and the configured proxy `CODEX_BASE_URL`. Inherited endpoint and sandbox defaults MUST NOT override the adapter's explicit effective execution settings; the selected sandbox mode MUST be recorded in the Python process contract.

#### Scenario: Proxied Codex request is made

- **WHEN** a Sandbox request targets the configured proxy host
- **THEN** HTTPS interception invokes the Worker egress hook, the Worker supplies the Bearer secret and logs only the injection event and hostname, and the sandbox-visible credential remains a placeholder

#### Scenario: Different deployers configure different proxy hosts

- **WHEN** two Worker configurations select different non-empty proxy hosts
- **THEN** each configuration registers credential injection only for its selected host
- **AND** an unconfigured environment registers no outbound host

## ADDED Requirements

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
