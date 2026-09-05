## MODIFIED Requirements

### Requirement: Discovery mode is selectable and agentic by default

Runtime-executing review, run, auto, gate, stack-review, and plan paths MUST select `agentic` discovery by default and MUST accept `inline` as an explicit fallback. The selected mode MUST propagate unchanged through planning and discovery. Sampling MUST continue to use the inline fixture path.

#### Scenario: Operator uses the default

- **WHEN** an ordinary review command omits discovery mode
- **THEN** it provisions or verifies a checkout and runs agentic discovery

#### Scenario: Operator selects legacy fallback

- **WHEN** an ordinary review command selects `inline`
- **THEN** the existing embedded-diff, exclusion, budget, and chunk behavior is used without requiring an agentic checkout

#### Scenario: Uncommitted review uses inline mode

- **WHEN** an operator selects inline discovery for an uncommitted target
- **THEN** the existing in-memory target diff remains reviewable

### Requirement: Routine review modes default to one replica

The `rvw review`, `rvw run`, and `rvw auto` commands MUST default to one discovery replica and three adjudication replicas. Commands that expose `--replicas` MUST use it only as the positive discovery replica count, MUST expose an independently positive `--adjudicate-replicas` count, and MUST preserve explicit values for each stage. `rvw plan` MUST report the discovery count as `replicas`, MUST report the adjudication count as `adjudicate_replicas`, and MUST calculate discovery run totals from the discovery count only.

#### Scenario: Review uses split defaults

- **WHEN** `rvw review` is invoked without replica overrides
- **THEN** the shared pipeline receives one discovery replica and three adjudication replicas

#### Scenario: Plan reports split routine defaults

- **WHEN** `rvw plan` renders a plan without replica overrides
- **THEN** its payload reports `replicas: 1` and `adjudicate_replicas: 3`, and its total discovery run count uses one run per active lane per diff chunk

#### Scenario: Discovery replication is explicitly requested

- **WHEN** a review command is invoked with `--replicas 2`
- **THEN** the shared pipeline receives two discovery replicas and the independently selected adjudication count

#### Scenario: Single-vote adjudication is explicitly requested

- **WHEN** a review command is invoked with `--adjudicate-replicas 1`
- **THEN** the shared pipeline preserves one adjudication replica without changing discovery dispatch, retry, widening, or voting rules

#### Scenario: Replica count is invalid

- **WHEN** either replica option is supplied with a value below one
- **THEN** the command rejects the invocation before executing the pipeline

### Requirement: Runtime-executing commands expose bounded concurrency

The `review`, `run`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--concurrency` with a default of 8, MUST reject values below 1 before runtime execution, and MUST propagate an explicit positive value to every discovery, adjudication, sampling, and stack-presence runtime wave they start.

#### Scenario: Review uses default concurrency

- **WHEN** `rvw review` is invoked without `--concurrency`
- **THEN** discovery and adjudication each receive a concurrency capacity of 8

#### Scenario: Operator lowers concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 3`
- **THEN** every runtime wave started by that command uses capacity 3 without changing replica counts

#### Scenario: Operator supplies zero concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 0`
- **THEN** CLI validation rejects the invocation before any runtime work starts

### Requirement: Runtime-executing commands expose bounded deadlines

The `review`, `run`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--deadline` with a default of 600, MUST reject values below 1 or above 1800 before runtime execution, and MUST propagate a permitted value as the base deadline to every discovery, adjudication, sampling, and stack-presence runtime path they start while preserving the established doubled deadline for an expanded pass.

#### Scenario: Review uses the default deadline

- **WHEN** `rvw review` is invoked without `--deadline`
- **THEN** discovery and adjudication each receive a base deadline of 600 seconds

#### Scenario: Operator raises the deadline to the ceiling

- **WHEN** a runtime-executing command is invoked with `--deadline 1800`
- **THEN** every runtime path started by that command receives 1800 seconds as its base deadline and an expanded pass receives 3600 seconds

#### Scenario: Operator supplies zero deadline

- **WHEN** a runtime-executing command is invoked with `--deadline 0`
- **THEN** CLI validation rejects the invocation before any runtime work starts

#### Scenario: Operator exceeds the deadline ceiling

- **WHEN** a runtime-executing command is invoked with `--deadline 1801`
- **THEN** CLI validation rejects the invocation before any runtime work starts

### Requirement: Review and auto share one pipeline

The `review`, `run`, and `auto` commands MUST use the same target-resolution, DISCOVER, MERGE, optional ADJUDICATE, and REPORT implementation. `auto` MUST be a compatibility alias for the policy-gated `run` execution, retaining policy-controlled publication unless an existing publication override is supplied.

#### Scenario: Auto review runs

- **WHEN** `rvw auto` is invoked for a target
- **THEN** it executes the same contract as `rvw run --policy auto` with publication selected by the effective policy or explicit override

### Requirement: Auto exposes a CI exit contract

The `run` and `auto` commands MUST reserve exit 0 for policy PASS, 1 for policy BLOCK, 2 for invalid input or configuration, and 3 for infrastructure failure. Invalid targets, anchor mismatches, absent explicitly selected policies, and invalid policy content MUST exit 2. Checkout, runtime, adjudication, publication, and unexpected execution exceptions MUST exit 3 and MUST NOT escape as exit 1. A failed review summary or zero VALID discovery coverage MUST exit 3 with a machine-readable `review_failed:<detail>` reason even when merge and adjudication are empty.

#### Scenario: Blocking keys exist

- **WHEN** successful execution produces a deterministic policy BLOCK
- **THEN** process status is `block` and the command exits 1

#### Scenario: All discovery lanes are invalid

- **WHEN** discovery has no VALID lane and produces no merged findings
- **THEN** the command persists `infra_failed` with exit 3 and `review_failed:<detail>` rather than PASS

#### Scenario: Policy path is missing

- **WHEN** an explicitly selected policy file does not exist
- **THEN** the command persists `invalid` and exits 2

#### Scenario: Adjudication or publication raises

- **WHEN** either stage raises an infrastructure exception
- **THEN** the command preserves available artifacts, persists `infra_failed`, and exits 3

### Requirement: CI composition preserves auto and publication semantics

Containerized GitHub Actions and App invocations MUST call `rvw run` and consume its canonical process and summary artifacts. They MUST preserve the reserved exit categories and COMMENT-only publication behavior, MUST NOT convert BLOCK or failed execution to success, and MUST NOT use stdout prose to determine the result.

#### Scenario: CI auto finds policy blockers

- **WHEN** containerized evaluation returns BLOCK and publishes finding narratives
- **THEN** the workflow job fails from exit 1 and the published review remains a COMMENT

## ADDED Requirements

### Requirement: Run is the shared policy-gated execution entry

`rvw run` MUST accept `--target <pr-url|pr-number|sha>`, optional `--base-ref` and `--head-ref`, optional `--repo-dir`, `--out`, `--policy auto|PATH`, `--publish none|github-comment`, and `--json`. It MUST expose positive discovery and adjudication replica controls with defaults 1 and 3, positive concurrency default 8, per-execution deadline default 600 seconds restricted to 1 through 1800, and discovery mode `agentic|inline` defaulting to `agentic`. It MUST execute the existing shared pipeline once, evaluate policy only after checking execution status, and record effective settings. `--out DIR` MUST name the artifact directory itself, with no appended run ID; without it the ordinary `/tmp/rvw/<run-id>` root MUST remain available. The run ID MUST remain recorded independently of the output path.

#### Scenario: Caller chooses an artifact directory

- **WHEN** `rvw run --out /workspace/result` completes
- **THEN** the process, summary, stage files, and runtime evidence are written beneath `/workspace/result` and its process contract still records the run ID

#### Scenario: Host caller supplies no checkout

- **WHEN** an agentic `run` invocation omits `--repo-dir`
- **THEN** existing provisioning supplies a verified checkout for shared discovery and adjudication

### Requirement: Run verifies supplied target anchors

For each supplied `--base-ref` or `--head-ref`, `run` and its alias MUST compare the resolved target SHA with the supplied SHA before review or publication. Any mismatch MUST return exit 2, status `invalid`, and failure code `target_anchor_mismatch` with expected and observed anchor detail. Without supplied anchors the commands MUST resolve the target through the ordinary resolver. Actions and App MUST supply both captured event anchors.

#### Scenario: PR head advances after the event

- **WHEN** resolved PR head differs from the event head passed through `--head-ref`
- **THEN** review and publication do not start and the process contract records `target_anchor_mismatch`

#### Scenario: PR base advances after the event

- **WHEN** resolved PR base differs from the supplied `--base-ref`
- **THEN** execution fails with the same invalid-input classification even when head is unchanged

### Requirement: PR URLs bind all GitHub operations to the target repository

When target resolution receives a PR URL, Python MUST bind subsequent GitHub PR metadata, diff, changed-file, and REST operations to the owner/repository in that URL through explicit repository arguments, repository-qualified REST paths, or a Python-owned subprocess environment. Ambient checkout identity or `GH_REPO` MUST NOT redirect those calls.

#### Scenario: Caller is in an unrelated checkout

- **WHEN** a PR URL names `owner/base` while cwd or ambient `GH_REPO` names another repository
- **THEN** every resulting GitHub PR operation remains bound to `owner/base`
