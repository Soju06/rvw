## MODIFIED Requirements

### Requirement: Routine review modes default to one replica

The `rvw review` and `rvw auto` commands MUST default to one discovery replica and three adjudication replicas. Commands that expose `--replicas` MUST use it only as the positive discovery replica count, MUST expose an independently positive `--adjudicate-replicas` count, and MUST preserve explicit values for each stage. `rvw plan` MUST report the discovery count as `replicas`, MUST report the adjudication count as `adjudicate_replicas`, and MUST calculate discovery run totals from the discovery count only.

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
