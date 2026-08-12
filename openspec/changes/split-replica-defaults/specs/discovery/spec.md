## MODIFIED Requirements

### Requirement: Discovery dispatch defaults to one replica

The DISCOVER stage MUST plan one run per active lane per diff chunk by default, independently of the adjudication replica count, and MUST dispatch all lane-replica-chunk runs through one shared wave. It MUST preserve the requested positive discovery count when callers explicitly request multiple replicas.

#### Scenario: Four lanes activate over two chunks

- **WHEN** discovery uses its default replica count while adjudication uses three replicas
- **THEN** discovery submits eight planned runs without waiting for one lane or chunk to finish before submitting another

#### Scenario: Three replicas are explicitly requested

- **WHEN** discovery is called with three replicas for four active lanes over two chunks
- **THEN** it submits 24 planned runs through the existing shared wave regardless of the adjudication replica count
