## ADDED Requirements

### Requirement: Discovery dispatch defaults to one replica

The DISCOVER stage MUST plan one run per active lane per diff chunk by default and MUST dispatch all lane-replica-chunk runs through one shared wave. It MUST preserve the requested count when callers explicitly request multiple replicas.

#### Scenario: Four lanes activate over two chunks

- **WHEN** discovery uses the default replica count
- **THEN** it submits eight planned runs without waiting for one lane or chunk to finish before submitting another

#### Scenario: Three replicas are explicitly requested

- **WHEN** discovery is called with three replicas for four active lanes over two chunks
- **THEN** it submits 24 planned runs through the existing shared wave

## REMOVED Requirements

### Requirement: Discovery dispatches three replicas by default

**Reason**: Ordinary review is now a single-pass scan; replication is an opt-in heavy-verification mode.

**Migration**: Call discovery with an explicit replica count greater than one when replicated verification is required.
