## ADDED Requirements

### Requirement: Lane prompts state the time and tool budget

Every discovery prompt built with a known dispatch deadline MUST state that deadline in seconds as the run's wall-clock budget and MUST state that the process is terminated when the budget expires and that any output not yet returned is lost. The prompt MUST require coverage of every changed region first and the final structured output immediately once every region is covered, and MUST declare exploration beyond the changed regions out of scope unless a finding's evidence requires it. Agentic prompts MUST additionally state a tool-call budget, 40 by default, as guidance rather than a hard limit, and MUST forbid fetching, cloning, or querying remote repositories or APIs because the base and head are available locally. Inline prompts, which run tool-less, MUST omit the tool-call and remote-access sentences. The budget text MUST be part of the structured-output instructions, MUST NOT name any deployer or repository, and MUST NOT alter the locale contract; a prompt built without a known deadline MUST be unchanged. The controller MUST NOT kill or invalidate a run for exceeding the tool-call budget.

#### Scenario: Agentic lane dispatched at 900 seconds

- **WHEN** agentic discovery dispatches a lane with a 900-second deadline
- **THEN** the prompt names a 900-second wall-clock budget, a budget of 40 tool calls, and the remote-access guard between the schema rules and the locale contract

#### Scenario: Inline lane dispatched at 600 seconds

- **WHEN** inline discovery dispatches a lane with a 600-second deadline
- **THEN** the prompt names a 600-second wall-clock budget and coverage-first, and omits the tool-call and remote-access sentences

#### Scenario: Lane exceeds the tool-call budget

- **WHEN** an agentic lane issues more tool commands than the stated budget
- **THEN** the run is classified only by the existing validity contract and its `tool_calls` count is recorded

## MODIFIED Requirements

### Requirement: Agentic discovery reviews an anchored repository range

Agentic discovery MUST be the default discovery mode, MUST require non-null base and head SHAs plus a verified checkout at the head, and MUST plan one logical run per active lane and requested replica without applying generated-path exclusions, per-file limits, aggregate diff budgets, or diff chunking. Each agentic prompt MUST contain only the lane document, a minimal statement identifying the `<base>...<head>` repository range, and structured-output instructions; those instructions include the configured locale contract and, when the dispatch deadline is known, the budget contract, and the prompt MUST contain nothing else. It MUST NOT contain unified-diff content, a materialized diff path, exclusion-glob guidance, a dynamic brief, or an already-covered-rules section.

#### Scenario: Large target uses one autonomous scope

- **WHEN** an agentic target diff is larger than the inline aggregate budget
- **THEN** discovery plans one run per lane and replica, reports no prompt budget, and gives each run the same verified repository range without embedding diff content

#### Scenario: Agentic target has no base

- **WHEN** an uncommitted or root-commit target without a base SHA is selected in agentic mode
- **THEN** discovery fails closed before runtime dispatch with a machine-readable checkout-verification reason

#### Scenario: Agentic prompt carries only the three sections

- **WHEN** an agentic lane is dispatched with a known deadline
- **THEN** its prompt consists of the lane document, the range statement, and the output instructions whose paragraphs are the schema rules, the budget contract, and the locale contract

### Requirement: Coverage receipts are verified and retried once

For each activated lane, discovery MUST union `covered` receipts only from VALID outputs, MUST treat a whole-file receipt as covering every controller-parsed hunk for that exact path, and MUST treat a `file:start-end` receipt as covering intersecting new-side hunk ranges for that exact path. If the per-lane union omits any target hunk after the initial dispatch and ordinary invalid-result retry, discovery MUST dispatch exactly one additional coverage wave containing one run for each incomplete lane that is not dead by timeout, MUST preserve that wave in a distinct artifact directory, and MUST NOT coverage-redispatch again. A lane is dead by timeout when it has zero VALID final planned executions and every final planned execution's final attempt is INVALID with reason `exit_nonzero:124`, regardless of the reasons recorded for its earlier attempts. Only `exit_nonzero:124` marks death: a lane whose final planned executions are INVALID with the transient runtime watchdog reason `no_output_after:<N>s` is NOT dead by timeout and keeps the ordinary retry and exactly one coverage-wave run. Discovery MUST NOT include a dead-by-timeout lane in the coverage wave and MUST record `redispatch_skipped: "dead_by_timeout"` on that lane's coverage. An incomplete lane whose final planned executions are all INVALID for any other reason, or whose final attempt was not the deadline kill, MUST still receive exactly one coverage-wave run, and a lane with at least one VALID but incomplete execution MUST keep the same single coverage-wave run. Discovery MUST enrich findings from valid coverage-wave outputs, recompute the receipt union, and persist every still-uncovered canonical hunk ID in the owning `LaneCoverage.uncovered` list.

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

#### Scenario: Runtime watchdog kills a lane twice

- **WHEN** a lane's initial attempt and its retry are both INVALID with reason `no_output_after:660s`
- **THEN** that lane receives exactly one coverage-wave run and `redispatch_skipped` remains null

#### Scenario: Watchdog kill then deadline kill

- **WHEN** a lane's initial attempt is INVALID with reason `no_output_after:660s` and its retry is INVALID with reason `exit_nonzero:124`
- **THEN** the lane is dead by timeout, discovery dispatches no coverage-wave run for it, and records `redispatch_skipped: "dead_by_timeout"`

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment, and the dispatcher MUST retry a lane-chunk group exactly once only when every initial replica for that lane and chunk is INVALID. The one replacement prompt for a retried lane-chunk MUST carry each prior replica's machine-readable invalid reason for that lane-chunk, and an initial wave prompt MUST NOT contain that retry feedback. The replacement wave MUST persist its artifacts in a run directory distinct from the initial wave's so the initial INVALID artifacts remain inspectable, while the directory's final component preserves the runtime replica-derivation contract. Persisted run coverage MUST record every attempt's validity and machine-readable invalid reason in execution order, while row-level validity continues to reflect the final attempt. Each persisted attempt MUST record its `wave` as `initial`, `retry`, or `coverage_redispatch` and the runtime `wall_seconds` when the runtime reported one; the attempts of a planned run MUST consist of one `initial` attempt followed only by `retry` attempts. Each persisted attempt MUST also record `tool_calls` and `assistant_messages` when the runtime usage reported them; these counts are telemetry and MUST NOT affect validity. Discovery artifacts persisted before attempt records existed MUST load with empty attempt history, attempt records persisted before `wave` existed MUST load as `initial` for attempt 1 and `retry` for later attempts with unknown wall time, and attempt records persisted before the telemetry fields existed MUST load with unknown counts.

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

#### Scenario: Attempt records carry tool-call telemetry

- **WHEN** a lane's runtime usage reports 7 tool calls and 2 assistant messages for an attempt
- **THEN** the persisted attempt records `tool_calls: 7` and `assistant_messages: 2`, and an attempt whose runtime reported no usage records both as null

#### Scenario: Attempt records without telemetry load

- **WHEN** a `discover.json` persisted before `tool_calls` and `assistant_messages` existed is loaded
- **THEN** loading succeeds and every attempt reports unknown counts
