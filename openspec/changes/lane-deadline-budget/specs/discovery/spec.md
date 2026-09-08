## MODIFIED Requirements

### Requirement: Coverage receipts are verified and retried once

For each activated lane, discovery MUST union `covered` receipts only from VALID outputs, MUST treat a whole-file receipt as covering every controller-parsed hunk for that exact path, and MUST treat a `file:start-end` receipt as covering intersecting new-side hunk ranges for that exact path. If the per-lane union omits any target hunk after the initial dispatch and ordinary invalid-result retry, discovery MUST dispatch exactly one additional coverage wave containing one run for each incomplete lane that is not dead by timeout, MUST preserve that wave in a distinct artifact directory, and MUST NOT coverage-redispatch again. A lane is dead by timeout when it has zero VALID final planned executions and every final planned execution's final attempt is INVALID with reason `exit_nonzero:124`, regardless of the reasons recorded for its earlier attempts. Discovery MUST NOT include a dead-by-timeout lane in the coverage wave and MUST record `redispatch_skipped: "dead_by_timeout"` on that lane's coverage. An incomplete lane whose final planned executions are all INVALID for any other reason, or whose final attempt was not the deadline kill, MUST still receive exactly one coverage-wave run, and a lane with at least one VALID but incomplete execution MUST keep the same single coverage-wave run. Discovery MUST enrich findings from valid coverage-wave outputs, recompute the receipt union, and persist every still-uncovered canonical hunk ID in the owning `LaneCoverage.uncovered` list.

#### Scenario: Initial receipt misses one hunk

- **WHEN** a lane's valid initial replicas collectively omit one controller hunk and its single coverage-wave run reports that hunk
- **THEN** that lane is coverage-redispatched once and persists an empty uncovered list

#### Scenario: Coverage remains incomplete

- **WHEN** the coverage-wave output still omits a controller hunk
- **THEN** discovery performs no third coverage wave and persists that canonical hunk ID as uncovered

#### Scenario: Invalid output claims coverage

- **WHEN** an INVALID run artifact contains or previously contained receipt-like data
- **THEN** none of that data contributes to verified coverage

#### Scenario: Lane dies at the deadline on both attempts

- **WHEN** a lane's initial attempt and its retry are both INVALID with reason `exit_nonzero:124`
- **THEN** discovery dispatches no coverage-wave run for that lane, records `coverage_redispatched: false` and `redispatch_skipped: "dead_by_timeout"`, and persists every target hunk as uncovered for that lane

#### Scenario: Lane fails twice for a non-timeout reason

- **WHEN** a lane's initial attempt and its retry are both INVALID with reason `exit_nonzero:1`
- **THEN** that lane receives exactly one coverage-wave run and `redispatch_skipped` remains null

#### Scenario: Lane recovers on retry but omits a hunk

- **WHEN** a lane's initial attempt is INVALID with reason `exit_nonzero:124` and its retry is VALID but omits a controller hunk
- **THEN** that lane receives exactly one coverage-wave run

#### Scenario: Capacity error precedes the deadline kill

- **WHEN** a lane's initial attempt is INVALID with a non-timeout reason and its retry is INVALID with reason `exit_nonzero:124`
- **THEN** discovery dispatches no coverage-wave run for that lane and records `redispatch_skipped: "dead_by_timeout"`

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment, and the dispatcher MUST retry a lane-chunk group exactly once only when every initial replica for that lane and chunk is INVALID. The one replacement prompt for a retried lane-chunk MUST carry each prior replica's machine-readable invalid reason for that lane-chunk, and an initial wave prompt MUST NOT contain that retry feedback. The replacement wave MUST persist its artifacts in a run directory distinct from the initial wave's so the initial INVALID artifacts remain inspectable, while the directory's final component preserves the runtime replica-derivation contract. Persisted run coverage MUST record every attempt's validity and machine-readable invalid reason in execution order, while row-level validity continues to reflect the final attempt. Each persisted attempt MUST record its `wave` as `initial`, `retry`, or `coverage_redispatch` and the runtime `wall_seconds` when the runtime reported one; the attempts of a planned run MUST consist of one `initial` attempt followed only by `retry` attempts. Discovery artifacts persisted before attempt records existed MUST load with empty attempt history, and attempt records persisted before `wave` existed MUST load as `initial` for attempt 1 and `retry` for later attempts with unknown wall time.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and performs no further retry

#### Scenario: Replacement prompt names prior failures

- **WHEN** every initial replica of one lane-chunk is INVALID with machine-readable reasons
- **THEN** that lane-chunk's replacement prompt lists each prior replica's invalid reason while another lane's unretried prompt contains none

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

#### Scenario: Retried coverage keeps the initial failure reason

- **WHEN** a lane-chunk retried after an initial `exit_nonzero` failure succeeds in the replacement wave
- **THEN** its persisted coverage row is valid, and its attempt records list the initial INVALID attempt with reason `exit_nonzero` followed by the valid retry attempt

#### Scenario: Attempt records carry wave and wall time

- **WHEN** a lane's initial attempt dies at the deadline after 600.06 seconds and its retry completes in 571.2 seconds
- **THEN** the persisted attempts are `{attempt: 1, wave: "initial", wall_seconds: 600.06}` and `{attempt: 2, wave: "retry", wall_seconds: 571.2}` with their validity and reasons

#### Scenario: Legacy discovery artifact loads

- **WHEN** a `discover.json` persisted before attempt records is loaded
- **THEN** loading succeeds and each coverage run reports empty attempt history

#### Scenario: Attempt records without a wave load

- **WHEN** a `discover.json` persisted with attempt records but no `wave` field is loaded
- **THEN** attempt 1 loads as `initial`, attempt 2 as `retry`, and both report unknown wall time

### Requirement: Discovery records per-lane coverage

Discovery MUST record each activated lane's aggregate planned dispatched, valid, and finding counts, MUST record exactly one strict run entry for every planned `(replica, chunk)` combination including zero-finding and INVALID results, and MUST record whether a bounded coverage re-dispatch occurred, the machine-readable reason when that re-dispatch was skipped, plus the ordered canonical hunk IDs still uncovered after it. A lane MUST NOT be recorded as both coverage-redispatched and skipped. Coverage-wave executions MUST be persisted on the owning lane as an ordered `redispatch` attempt list tagged `coverage_redispatch` with validity, machine-readable reason, and wall time; that list MUST be empty unless the lane was coverage-redispatched, and coverage-wave executions MUST remain separately inspectable without changing the planned run identity set.

#### Scenario: One chunk remains invalid

- **WHEN** a two-chunk, three-replica lane has five VALID final results and one INVALID final result
- **THEN** coverage reports six dispatched, five valid, and six distinct run entries identifying the invalid replica-chunk combination

#### Scenario: Agentic lane remains incomplete

- **WHEN** an agentic lane's initial and coverage-wave receipts omit one hunk
- **THEN** coverage retains its planned lane-replica run entries, marks coverage re-dispatch true, and lists the omitted canonical hunk ID

#### Scenario: Dead lane is not redispatched

- **WHEN** an agentic lane is dead by timeout after its retry
- **THEN** coverage marks coverage re-dispatch false, records `redispatch_skipped: "dead_by_timeout"`, an empty `redispatch` list, and lists every target hunk as uncovered

#### Scenario: Coverage wave is inspectable

- **WHEN** an agentic lane is coverage-redispatched and its coverage-wave run ends INVALID with reason `exit_nonzero:1` after 101.5 seconds
- **THEN** the lane's planned run entries are unchanged and its `redispatch` list holds one attempt tagged `coverage_redispatch` with that reason and wall time
