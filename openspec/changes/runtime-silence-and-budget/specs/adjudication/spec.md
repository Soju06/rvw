## ADDED Requirements

### Requirement: Replica silence is bounded by the runtime watchdog

Each adjudication replica execution MUST inherit the runtime no-output watchdog. A replica terminated for silence MUST be INVALID with reason `no_output_after:<N>s` and MUST cast no vote. The pass MUST NOT retry while at least one replica of the wave is VALID, so the wave wall is bounded by the slowest valid replica wall or by `N` plus the watchdog poll interval and termination grace, rather than by the deadline; when every replica of the wave is terminated for silence, the existing single all-invalid retry applies and its prompt carries those reasons.

#### Scenario: One replica never produces output

- **WHEN** one of three replicas prints only its banner and prompt echo while the other two answer before `N` seconds have elapsed
- **THEN** the silent replica is INVALID with reason `no_output_after:<N>s`, voting uses the two valid outputs, no retry wave runs, and the recorded wave wall is bounded by `N` plus the poll interval and termination grace rather than by the deadline

#### Scenario: Every replica is silent

- **WHEN** all three replicas of a wave are terminated by the watchdog
- **THEN** each is INVALID with a `no_output_after` reason and exactly one retry wave runs with a prompt carrying those reasons
