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

### Requirement: Discovery records per-lane coverage

Discovery MUST record each activated lane's aggregate planned dispatched, valid, and finding counts, MUST record exactly one strict run entry for every planned `(replica, chunk)` combination including zero-finding and INVALID results, and MUST record whether a bounded coverage re-dispatch occurred, the machine-readable reason when that re-dispatch was skipped, plus the ordered canonical hunk IDs still uncovered after it. A lane MUST NOT be recorded as both coverage-redispatched and skipped. Coverage-wave executions MUST remain separately inspectable without changing the planned run identity set.

#### Scenario: One chunk remains invalid

- **WHEN** a two-chunk, three-replica lane has five VALID final results and one INVALID final result
- **THEN** coverage reports six dispatched, five valid, and six distinct run entries identifying the invalid replica-chunk combination

#### Scenario: Agentic lane remains incomplete

- **WHEN** an agentic lane's initial and coverage-wave receipts omit one hunk
- **THEN** coverage retains its planned lane-replica run entries, marks coverage re-dispatch true, and lists the omitted canonical hunk ID

#### Scenario: Dead lane is not redispatched

- **WHEN** an agentic lane is dead by timeout after its retry
- **THEN** coverage marks coverage re-dispatch false, records `redispatch_skipped: "dead_by_timeout"`, and lists every target hunk as uncovered
