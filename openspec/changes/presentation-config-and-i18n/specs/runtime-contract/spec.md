## ADDED Requirements

### Requirement: Execution contracts retain presentation and language publication outcomes

The shared process and summary contracts MUST expose the resolved strict `presentation` configuration, nullable nonempty-string `publication_failure` defaulting to null, and boolean `language_fallback_used` defaulting to false so adapters and replay consume the same snapshot. Missing presentation in a legacy retained run MUST resolve to the documented rvw/en defaults. Invalid configured presentation MUST produce `presentation_config_invalid` with invalid status and exit 2 before runtime dispatch. Persistent publication language mismatch MUST produce `publication_language_mismatch` with `infra_failed` status and exit 3 while retaining review evidence and localized counts; fallback use MUST be recorded as `language_fallback_used: true`. A rewrite MUST use the existing bounded read-only runtime abstraction with an injectable prose-only rewriting interface and strict segment-count validation. Publication attempts MUST persist `publication.json` with failure, fallback-use, and rewrite-attempt facts without mutating diagnostic finding or adjudication artifacts. Legacy process and summary contracts without the publication fields MUST load with null failure and false fallback.

#### Scenario: Invalid presentation before discovery

- **WHEN** target anchoring succeeds but presentation validation fails
- **THEN** the process retains presentation_config_invalid with invalid status and exit 2, the summary remains incomplete, and no model runs

#### Scenario: Language rewrite fails

- **WHEN** publication still mismatches after one bounded rewrite
- **THEN** the process reports infrastructure failure and exit 3 with publication_language_mismatch while retained adjudication evidence is unchanged

## MODIFIED Requirements

### Requirement: Policy-gated execution owns a versioned process envelope

Python MUST initialize `process.json` before target resolution and finalize it for every `run` or `auto` termination for which the artifact directory can be written. Its strict version-1 schema MUST contain `schema_version: 1`, string `run_id`, `target` with nullable `repo`, `pr`, `base`, and `head`, `status` in `pass|block|invalid|infra_failed`, the corresponding integer `exit_code` in `0|1|2|3`, nonnegative integer `duration_ms`, canonical argument-array `command`, `effective_policy` with nullable `source` and `path`, a `lane_sources` count mapping, `runtime` effective settings, nullable `failure` with `code` and `detail`, resolved `presentation`, nullable nonempty-string `publication_failure` defaulting to null, boolean `language_fallback_used` defaulting to false, an `artifacts` array of relative `path` and nonnegative `size_bytes` records, and nullable `sdk_observations` with nullable `exit_code`, `signal`, `duration_ms`, and wrapper `command`. Policy source MUST be `explicit`, `repository`, `external`, or `package` when known. Runtime settings MUST include `replicas`, `adjudicate_replicas`, `concurrency`, `deadline`, `discovery_mode`, `publish`, `host_concurrency`, and `sandbox`. Before completion, the envelope MUST default to `infra_failed`, exit 3, and failure `execution_incomplete`; it MUST never predeclare PASS. Adapters MUST consume this envelope rather than manufacture a competing result format.

#### Scenario: Resolution fails before discovery

- **WHEN** target resolution fails after artifact-root initialization
- **THEN** `process.json` still identifies the run, selected settings, failure and reserved exit code, with unknown target and policy fields null

#### Scenario: Execution is forcibly stopped

- **WHEN** an adapter observes forced termination after Python initialized its contract
- **THEN** the incomplete envelope remains a failure and the adapter merges SDK-observed supplemental termination evidence into that same contract without inventing a policy verdict
