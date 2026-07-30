## ADDED Requirements

### Requirement: Target gate defaults to one replica

The `rvw gate --target <pr>` command MUST execute its shared review pipeline with one replica by default and MUST preserve an explicit positive `--replicas` count for opt-in replicated verification.

#### Scenario: Target gate uses its default replica count

- **WHEN** `rvw gate --target <pr>` is invoked without `--replicas`
- **THEN** its gate plan records one replica and its shared review pipeline receives one replica

#### Scenario: Target gate explicitly requests replication

- **WHEN** `rvw gate --target <pr> --replicas 3` is invoked
- **THEN** its gate plan records three replicas and its shared review pipeline receives three replicas
