## ADDED Requirements

### Requirement: Routine review modes default to one replica

The `rvw review` and `rvw auto` commands MUST default to one discovery and adjudication replica, and `rvw plan` MUST report one replica in its payload and calculate default total runs from that count. Review commands that expose `--replicas` MUST accept an explicit positive count and MUST preserve replicated execution when the count is greater than one.

#### Scenario: Review uses its default replica count

- **WHEN** `rvw review` is invoked without `--replicas`
- **THEN** the shared pipeline receives one replica for discovery and adjudication

#### Scenario: Plan reports the routine default

- **WHEN** `rvw plan` renders a plan without a replica override
- **THEN** its payload reports `replicas: 1` and its total run count uses one run per active lane per diff chunk

#### Scenario: Replication is explicitly requested

- **WHEN** a review command is invoked with `--replicas 3`
- **THEN** the shared pipeline receives three replicas without changing dispatch, retry, widening, or voting behavior
