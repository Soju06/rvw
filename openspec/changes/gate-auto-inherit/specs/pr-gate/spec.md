## ADDED Requirements

### Requirement: Fresh PR gates automatically select prior dispositions

When `rvw gate --target <pr>` is invoked without `--inherit`, without `--no-inherit`, and without `--run`, gate MUST search the configured output root for the most recent prior gate run of the same repository and pull-request number that records validated completed dispositions. It MUST select the qualifying candidate with the latest run-ID timestamp, MUST announce the selected run identifier, and MUST process it through the same validation, matching, summary, and provenance behavior as explicit inheritance.

Gate MUST exclude the current run, non-pull-request targets, runs for another repository or pull-request number, and runs without validated completed dispositions. Repository identity comparison MUST be case-insensitive. A newer nonqualifying candidate MUST NOT prevent selection of an older qualifying candidate.

#### Scenario: Most recent qualifying run is surrounded by decoys

- **WHEN** the output root contains a qualifying same-repository and same-PR completed run plus newer runs for another PR, another repository, a commit target, and a run without dispositions
- **THEN** gate selects the most recent qualifying same-PR run and records its identifier through the existing inheritance provenance

#### Scenario: No qualifying prior run exists

- **WHEN** fresh target mode finds no prior same-repository and same-PR run with validated completed dispositions
- **THEN** gate emits one informational line and proceeds without inheritance or an error

#### Scenario: Automatic selection cannot choose the current run

- **WHEN** the newly allocated run is visible below the output root during discovery
- **THEN** gate excludes that run identifier from candidate selection

### Requirement: Gate inheritance selection has explicit precedence and opt-out

The `rvw gate` command MUST accept `--no-inherit` to disable automatic source discovery. An explicit `--inherit <run-id>` MUST be used instead of automatic discovery, and supplying `--inherit` together with `--no-inherit` MUST be rejected as an invalid invocation with a clear message and nonzero exit. Resume mode MUST NOT perform automatic discovery.

#### Scenario: Automatic inheritance is disabled

- **WHEN** fresh target mode is invoked with `--no-inherit` while a qualifying prior run exists
- **THEN** gate performs no automatic discovery and proceeds without an inherited source

#### Scenario: Explicit source wins

- **WHEN** fresh target mode supplies `--inherit <run-id>` while a newer qualifying source exists
- **THEN** gate uses the explicitly named run and does not replace it through automatic discovery

#### Scenario: Conflicting selection options are supplied

- **WHEN** an invocation supplies both `--inherit <run-id>` and `--no-inherit`
- **THEN** gate exits nonzero with a clear usage error before inheritance processing
