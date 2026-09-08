## ADDED Requirements

### Requirement: The job deadline covers the review budget

The Worker MUST read `RVW_REVIEW_DEADLINE_SECONDS` as a whole number of seconds between 1 and 1800 and MUST fail closed with `config_missing` or `config_invalid` when it is absent or out of range. It MUST read `RVW_JOB_DEADLINE_MINUTES` as a positive whole number of minutes when present, MUST use 90 when it is absent, and MUST fail closed with `config_invalid` when it is present but malformed. At configuration load, before serving any request or queue batch, the Worker MUST require `RVW_JOB_DEADLINE_MINUTES * 60 >= 5 * RVW_REVIEW_DEADLINE_SECONDS + 600` and MUST fail closed with the machine-readable code `config_incoherent` and reason `job_deadline_below_review_budget`, naming the configured minutes, the review deadline, and the minimum minutes required, when the inequality does not hold. The committed Wrangler configuration MUST satisfy that inequality for the default, `spike`, and `prod` environments, and the job deadline recorded at review start MUST come from the same validated configuration.

#### Scenario: Committed configuration is coherent

- **WHEN** the committed vars set `RVW_REVIEW_DEADLINE_SECONDS` to `900` and `RVW_JOB_DEADLINE_MINUTES` to `120`
- **THEN** configuration loads and jobs record a 120-minute deadline

#### Scenario: Deployer lowers the job cap below the budget

- **WHEN** a deployer overlays `RVW_JOB_DEADLINE_MINUTES=84` while the review deadline stays `900`
- **THEN** every request and queue batch fails closed with `config_incoherent` and `job_deadline_below_review_budget` reporting a minimum of 85 minutes, and no review starts

#### Scenario: Review deadline is out of range

- **WHEN** `RVW_REVIEW_DEADLINE_SECONDS` is `1801`, `0`, or not a whole number
- **THEN** configuration fails closed with `config_invalid` naming that variable

#### Scenario: Job cap is malformed

- **WHEN** `RVW_JOB_DEADLINE_MINUTES` is present but is `soon`, `0`, or `90.5`
- **THEN** configuration fails closed with `config_invalid` naming `RVW_JOB_DEADLINE_MINUTES` instead of silently using a default

## MODIFIED Requirements

### Requirement: App review execution consumes the shared run contract

The App MUST invoke `rvw run` with the complete PR URL, captured webhook base and head SHAs, an explicit publication mode, an explicit `--deadline` equal to the Worker var `RVW_REVIEW_DEADLINE_SECONDS`, and `--out /workspace/result`; it MUST NOT rely on the CLI default deadline, and the A0 spike review script MUST pass the same explicit deadline. The container entrypoint MUST forward that argument verbatim so `process.json` records the same value under `runtime.deadline`. Python MUST own repository binding, policy fallback, result classification, summary aggregation, and artifact discovery. The App MUST consume `process.json`, `summary.json`, and its manifest without parsing stdout for a verdict or run ID, copying from a guessed `/tmp/rvw` directory, or recounting discovery and adjudication results. The App MUST retain webhook validation, installation-token injection, Check Run API, queue and Durable Object lifecycle, Sandbox allocation/destruction, and R2 transport responsibilities.

#### Scenario: Webhook head is stale

- **WHEN** the current PR differs from the captured webhook anchors
- **THEN** Python returns `target_anchor_mismatch` and the App completes a neutral Check for the captured webhook head

#### Scenario: Review deadline is explicit

- **WHEN** `RVW_REVIEW_DEADLINE_SECONDS` is `900` and the App starts a review
- **THEN** the review script executes `rvw run` with `--deadline 900`, and the resulting `process.json` records `runtime.deadline: 900`
