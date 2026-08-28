## MODIFIED Requirements

### Requirement: Discovery dispatch defaults to one replica

The DISCOVER stage MUST plan one run per active lane per diff chunk by default,
independently of the adjudication replica count, and MUST dispatch all
lane-replica-chunk runs through one shared wave. It MUST preserve the requested
positive discovery count when callers explicitly request multiple replicas. One
shared pure planning operation MUST load active lanes, apply the diff budget,
derive the effective brief, and build every initial lane prompt used for both
preflight accounting and dispatch. The planner MUST expose exact aggregate
initial prompt characters and the one-retry upper bound of twice its initial
run count; retry-feedback characters are excluded because invalid reasons do
not exist before execution.

#### Scenario: Four lanes activate over two chunks

- **WHEN** discovery uses its default replica count while adjudication uses
  three replicas
- **THEN** it submits eight planned runs without waiting for one lane or chunk
  to finish before submitting another

#### Scenario: Three replicas are explicitly requested

- **WHEN** discovery is called with three replicas for four active lanes over
  two chunks
- **THEN** it submits 24 planned runs through the existing shared wave
  regardless of the adjudication replica count

#### Scenario: Preflight and dispatch share a plan

- **WHEN** a target activates four lanes with three discovery replicas over one
  chunk
- **THEN** preflight reports 12 initial runs, 24 retry-upper-bound runs, and
  the exact sum of the twelve prompts that dispatch will send
