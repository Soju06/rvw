## ADDED Requirements

### Requirement: Runtime-executing commands expose bounded deadlines

The `review`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--deadline` with a default of 600, MUST reject values below 1 or above 1800 before runtime execution, and MUST propagate a permitted value as the base deadline to every discovery, adjudication, sampling, and stack-presence runtime path they start while preserving the established doubled deadline for an expanded pass.

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
