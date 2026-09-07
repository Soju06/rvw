## MODIFIED Requirements

### Requirement: Policy-gated summaries have one producer

Python MUST emit version-1 `summary.json` with `schema_version: 1`, `lanes` counts `dispatched`, `valid`, and `uncovered`, `findings` counts for `blocker`, `warning`, and `suggestion`, `verdicts` counts for `CONFIRMED`, `REJECTED`, and `UNCERTAIN`, a `blockers` list of policy-blocking finding identifiers, and common `markdown` summary text. `lanes.dispatched` MUST count dispatched lanes, `lanes.valid` MUST count lanes with at least one VALID execution, and `lanes.uncovered` MUST count remaining lane-hunk receipts. Counts MUST be derived from persisted execution and finding evidence, MUST preserve zero-valid coverage distinctly from clean valid execution, and MUST remain available with partial or missing stage artifacts. Missing execution evidence MUST NOT imply a successful review. App Check summaries and every other presentation of a policy-gated run MUST consume these facts without recounting stage payloads. `outcome.json` MUST retain its adjudication schema.

#### Scenario: Valid execution finds nothing

- **WHEN** one or more discovery lanes are valid and no findings survive
- **THEN** the summary records positive valid coverage and zero finding and verdict counts

#### Scenario: Review never reaches adjudication

- **WHEN** execution fails before adjudication
- **THEN** the summary remains available, the process envelope records failure, and absent verdict evidence is not interpreted as PASS
