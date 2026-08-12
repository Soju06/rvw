## MODIFIED Requirements

### Requirement: Target gate defaults to one replica

The `rvw gate --target <pr>` command MUST execute its shared review pipeline with one discovery replica and three adjudication replicas by default. It MUST preserve explicit positive `--replicas` and `--adjudicate-replicas` values independently, MUST record both values in its gate plan while retaining `replicas` as the discovery count, and MUST validate coverage against discovery replicas only.

#### Scenario: Target gate uses its split defaults

- **WHEN** `rvw gate --target <pr>` is invoked without replica overrides
- **THEN** its gate plan records `replicas: 1` and `adjudicate_replicas: 3`, and its shared review pipeline receives those counts for the corresponding stages

#### Scenario: Target gate explicitly requests split replication

- **WHEN** `rvw gate --target <pr> --replicas 2 --adjudicate-replicas 1` is invoked
- **THEN** its gate plan records two discovery replicas and one adjudication replica, and coverage expects only the two discovery replica identities per lane and chunk
