## MODIFIED Requirements

### Requirement: Pipeline artifacts are file-first

Every review run MUST create a unique directory under `/tmp/rvw/` by default or use its supplied artifact directory and MUST persist target, discovery, merge, optional adjudication, and report artifacts before publication uses them. Ordinary run identifiers MUST carry a sub-second timestamp component, and default-directory creation MUST resolve a residual run-directory name collision by regenerating the identifier instead of failing, while remaining safe for run-ID validation and reopening. For `run` and `auto`, `--out` MUST select the artifact directory itself and MUST NOT append the run ID.

#### Scenario: PR review completes

- **WHEN** a PR review reaches REPORT with the default output root
- **THEN** its `/tmp/rvw/<run-id>/` directory contains `target.json`, `discover.json`, `merge.json`, optional `outcome.json`, and `report.md`

#### Scenario: Two runs start on the same target in the same second

- **WHEN** two review runs are created for the same pull request within one second
- **THEN** both receive distinct default run directories and neither creation fails

#### Scenario: Adapter supplies a result directory

- **WHEN** `rvw run --out /workspace/result` starts
- **THEN** its artifacts are directly addressable beneath `/workspace/result` without stdout parsing or a copying stage

## ADDED Requirements

### Requirement: Policy-gated summaries have one producer

Python MUST emit version-1 `summary.json` with `schema_version: 1`, `lanes` counts `dispatched`, `valid`, and `uncovered`, `findings` counts for `blocker`, `warning`, and `suggestion`, `verdicts` counts for `CONFIRMED`, `REJECTED`, and `UNCERTAIN`, a `blockers` list of policy-blocking finding identifiers, and common `markdown` summary text. `lanes.dispatched` MUST count dispatched lanes, `lanes.valid` MUST count lanes with at least one VALID execution, and `lanes.uncovered` MUST count remaining lane-hunk receipts. Counts MUST be derived from persisted execution and finding evidence, MUST preserve zero-valid coverage distinctly from clean valid execution, and MUST remain available with partial or missing stage artifacts. Missing execution evidence MUST NOT imply a successful review. App Check summaries and Actions step summaries MUST consume these facts without recounting stage payloads. `outcome.json` MUST retain its adjudication schema.

#### Scenario: Valid execution finds nothing

- **WHEN** one or more discovery lanes are valid and no findings survive
- **THEN** the summary records positive valid coverage and zero finding and verdict counts

#### Scenario: Review never reaches adjudication

- **WHEN** execution fails before adjudication
- **THEN** the summary remains available, the process envelope records failure, and absent verdict evidence is not interpreted as PASS

### Requirement: The process manifest enumerates all retained files

The final `process.json` artifact manifest MUST enumerate every regular file written beneath the artifact directory, including top-level contracts, diagnostics, stage files, and nested runtime evidence. Entries MUST use unique output-relative paths and exact final byte sizes, MUST be deterministically sorted, and MUST include `process.json` with its own correct serialized size. Manifest paths MUST NOT traverse outside the artifact directory or name symlinks. Adapters MUST discover retained review artifacts through this manifest instead of an independent hardcoded artifact-name list.

#### Scenario: Runtime evidence is nested

- **WHEN** discovery writes per-replica prompt, schema, output, log, and usage files
- **THEN** the final manifest includes every retained nested file with its output-relative path and actual size

#### Scenario: Adapter uploads a failed review

- **WHEN** review ends before later stage files exist
- **THEN** the manifest lists the files actually retained, and uploading those files does not require absent later-stage artifacts
