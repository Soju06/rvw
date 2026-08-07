## MODIFIED Requirements

### Requirement: Dispatch is bounded and heavy-first

The dispatcher MUST sort runs heavy, normal, then light, MUST bound concurrent runtime executions with a semaphore whose default capacity is 8, and MUST preserve an explicitly requested positive capacity.

#### Scenario: Heavy and light lanes share a plan

- **WHEN** semaphore capacity becomes available at the start of a wave
- **THEN** heavy lane runs are queued before normal and light lane runs while in-flight work never exceeds 8 by default

#### Scenario: Caller overrides concurrency

- **WHEN** discovery is called with concurrency 3
- **THEN** in-flight runtime executions never exceed 3
