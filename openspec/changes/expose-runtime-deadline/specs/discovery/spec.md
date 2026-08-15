## MODIFIED Requirements

### Requirement: Dispatch is bounded and heavy-first

The dispatcher MUST sort runs heavy, normal, then light, MUST bound concurrent runtime executions with a semaphore whose default capacity is 8, and MUST preserve an explicitly requested positive capacity. Each dispatched runtime execution MUST receive a deadline of 600 seconds by default and MUST preserve an explicitly requested positive deadline. When the host-global slot gate is enabled, each runtime execution MUST additionally hold one host-global slot for its duration, so in-flight executions never exceed the smaller of the per-process capacity and the host cap.

#### Scenario: Heavy and light lanes share a plan

- **WHEN** semaphore capacity becomes available at the start of a wave
- **THEN** heavy lane runs are queued before normal and light lane runs while in-flight work never exceeds 8 by default

#### Scenario: Caller overrides concurrency

- **WHEN** discovery is called with concurrency 3
- **THEN** in-flight runtime executions never exceed 3

#### Scenario: Host cap is lower than process capacity

- **WHEN** the host-global cap is 2 and discovery runs with process concurrency 8
- **THEN** in-flight runtime executions never exceed 2 and every slot is released when its execution finishes or fails

#### Scenario: Runtime uses the default deadline

- **WHEN** discovery is called without an explicit deadline
- **THEN** every initial and replacement dispatch receives a deadline of 600 seconds
