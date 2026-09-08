## ADDED Requirements

### Requirement: Execution summaries expose lane failures and per-wave wall time

Version-1 `summary.json` MUST include `failed_lanes`, an ordered list of `{lane_id, reason}` records naming every lane with at least one final INVALID planned execution, where `reason` is the final normalized machine-readable reason and distinct reasons across one lane's failed executions are joined with `, ` in execution order; lanes whose final planned executions are all VALID MUST be absent. It MUST include `wave_wall_seconds` with exactly the keys `discovery_initial`, `discovery_retry`, `discovery_redispatch`, `adjudication_initial`, `adjudication_initial_retry`, `adjudication_expanded`, and `adjudication_expanded_retry`, each holding the longest runtime `wall_seconds` recorded for that wave or null when the wave did not run or reported no wall time. Discovery waves MUST be derived from persisted attempt records and `redispatch` lists; adjudication waves MUST be derived from `outcome.json`, whose `wave_wall_seconds` MUST map each executed adjudication wave label (`initial`, `initial-retry`, `expanded`, `expanded-retry`) to the longest replica wall of that wave without changing verdict semantics. Legacy summary and outcome artifacts without these fields MUST load with an empty failed-lane list, null waves, and no adjudication wave telemetry. Adapters MUST consume these facts without recounting stage artifacts.

#### Scenario: Two lanes die at the deadline

- **WHEN** `correctness` ends `exit_nonzero:124` on both attempts, `hygiene` ends `exit_nonzero:1` then `exit_nonzero:124`, and neither is redispatched
- **THEN** `failed_lanes` is `[{lane_id: "correctness", reason: "exit_nonzero:124"}, {lane_id: "hygiene", reason: "exit_nonzero:124"}]`, `discovery_initial` and `discovery_retry` hold the longest attempt walls of their waves, and `discovery_redispatch` is null

#### Scenario: Adjudication needed an expanded pass

- **WHEN** the initial adjudication wave completes and one uncertain group runs the expanded pass
- **THEN** `outcome.json` records `initial` and `expanded` wave walls, the summary mirrors them as `adjudication_initial` and `adjudication_expanded`, and the retry waves are null

#### Scenario: Legacy artifacts load

- **WHEN** a `summary.json` or `outcome.json` persisted before these fields is loaded
- **THEN** loading succeeds with an empty failed-lane list, null wave walls, and empty adjudication wave telemetry
