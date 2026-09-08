# discovery

## Purpose

Define target preparation, gap-coverage prompting, replicated dispatch, dynamic-brief fallback, and bounded diff handling for the DISCOVER stage.

## Requirements

### Requirement: The unscoped sweep is an always-active base lane

The runtime registry MUST register `unscoped-sweep` in a predicate-free base layer, and its lane schema MUST cap emitted severity at `warning`.

#### Scenario: Project has many scoped lanes

- **WHEN** a target activates project, scope, and dynamic lanes
- **THEN** `unscoped-sweep` is still dispatched and cannot emit a blocker-severity finding

### Requirement: Sweep prompts receive covered rules

In inline mode, a lane declaring `covered_by_others: inject` MUST receive every other active lane's rule IDs in an already-covered section and MUST be instructed not to re-report those classes. Agentic mode MUST omit this separate section to preserve its minimal prompt contract.

#### Scenario: Two other lanes are active inline

- **WHEN** the sweep runs in inline mode beside security and schema lanes
- **THEN** its prompt names both lanes and their rule IDs as already covered

#### Scenario: Sweep runs agentically

- **WHEN** the sweep runs in agentic mode
- **THEN** its prompt contains its lane document and no separately injected already-covered section

### Requirement: Agentic discovery reviews an anchored repository range

Agentic discovery MUST be the default discovery mode, MUST require non-null base and head SHAs plus a verified checkout at the head, and MUST plan one logical run per active lane and requested replica without applying generated-path exclusions, per-file limits, aggregate diff budgets, or diff chunking. Each agentic prompt MUST contain only the lane document, a minimal statement identifying the `<base>...<head>` repository range, and structured-output instructions including the configured locale contract; it MUST NOT contain unified-diff content, a materialized diff path, exclusion-glob guidance, a dynamic brief, or an already-covered-rules section.

#### Scenario: Large target uses one autonomous scope

- **WHEN** an agentic target diff is larger than the inline aggregate budget
- **THEN** discovery plans one run per lane and replica, reports no prompt budget, and gives each run the same verified repository range without embedding diff content

#### Scenario: Agentic target has no base

- **WHEN** an uncommitted or root-commit target without a base SHA is selected in agentic mode
- **THEN** discovery fails closed before runtime dispatch with a machine-readable checkout-verification reason

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

### Requirement: Discovery dispatch defaults to one replica

The DISCOVER stage MUST plan one run per active lane per inline diff chunk or per active lane agentic scope by default, independently of the adjudication replica count, and MUST dispatch all planned lane-replica-scope runs through one shared wave. It MUST preserve the requested positive discovery count when callers explicitly request multiple replicas.

#### Scenario: Four inline lanes activate over two chunks

- **WHEN** inline discovery uses its default replica count while adjudication uses three replicas
- **THEN** it submits eight planned runs without waiting for one lane or chunk to finish before submitting another

#### Scenario: Four agentic lanes activate

- **WHEN** agentic discovery uses its default replica count while adjudication uses three replicas
- **THEN** it submits four planned initial runs regardless of target diff size

#### Scenario: Three replicas are explicitly requested

- **WHEN** agentic discovery is called with three replicas for four active lanes
- **THEN** it submits 12 planned initial runs through the existing shared wave regardless of the adjudication replica count

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

### Requirement: Dynamic brief falls back to PR claims

In inline mode, dynamic lanes MUST use an operator-supplied brief when present, SHALL otherwise use the PR title and body when available, and MUST label the PR-derived brief as an UNVERIFIED claim of intent. Agentic mode MUST omit a separately injected brief from the runtime prompt.

#### Scenario: No operator brief for an inline PR

- **WHEN** an inline PR target has a title and body but no `--dynamic-brief`
- **THEN** dynamic prompts contain the title/body and the UNVERIFIED note

#### Scenario: No brief source exists inline

- **WHEN** an inline commit target has no operator brief
- **THEN** dynamic prompts state that the brief is unavailable and findings should be marked inconclusive

#### Scenario: Agentic dynamic lane runs

- **WHEN** a dynamic lane executes in agentic mode
- **THEN** its prompt omits operator and PR-derived brief sections

### Requirement: Generated and oversized files are visibly excluded

Inline discovery MUST exclude default generated globs (`**/runtime-snapshots/**`, `**/*.generated.*`, `**/generated/**`, lockfiles, `**/dist/**`, and `**/__snapshots__/**`) and per-file diffs above 200,000 characters, MUST retain exact kept/excluded character accounting, and MUST prepend a visible exclusion header to the review diff. Agentic discovery MUST NOT apply these prompt-sizing exclusions.

#### Scenario: Generated snapshot dominates an inline diff

- **WHEN** a generated snapshot matches a configured glob in inline mode
- **THEN** it is absent from lane diff content, appears in the exclusion report with reason `generated-path`, and is named in the visible header

#### Scenario: Generated path exists in agentic range

- **WHEN** an agentic target changes a path that matches an inline exclusion glob
- **THEN** the controller gives no exclusion instruction and the agent may inspect the path from the checkout

### Requirement: Diff budget plans ordered file chunks

In inline discovery, after generated-path and oversized-file exclusions, discovery MUST partition complete kept file segments with order-preserving greedy next-fit packing, MUST place every kept file in exactly one chunk, and MUST keep each chunk's retained segment characters at or below 400,000. The inline planner MUST return one chunk when the retained diff fits, MUST preserve that filtered diff byte-for-byte, and MUST record ordered chunk count, file placement, and character accounting. The same module MUST additionally expose an unpartitioned reviewed-diff projection that returns the concatenated kept segments behind the visible exclusion header together with the same exclusion report, so post-discovery stages apply one shared exclusion policy rather than re-implementing it. Agentic discovery MUST NOT consult this planner for prompt sizing.

#### Scenario: Ordinary inline diff fits one chunk

- **WHEN** inline retained file segments total at most 400,000 characters
- **THEN** the planner returns one chunk whose diff bytes equal the previously filtered result

#### Scenario: Large inline source diff requires multiple chunks

- **WHEN** inline retained file segments total about 735,000 characters and every file is at most 200,000 characters
- **THEN** the planner returns at least two chunks in source order, every chunk is at most 400,000 retained characters, and every kept file appears exactly once

#### Scenario: A post-discovery stage requests the reviewed diff

- **WHEN** a caller requests the reviewed-diff projection for a target whose diff contains one generated file and one kept file
- **THEN** it receives the kept segment behind the exclusion header plus the exclusion report, and the generated segment is absent

#### Scenario: Large agentic source range

- **WHEN** the same source range is reviewed agentically
- **THEN** discovery performs no diff-budget planning and retains one logical scope per lane and replica

### Requirement: Chunk prompts expose the whole file plan

Every inline discovery prompt MUST identify its `chunk k/N`, MUST list every kept file path in source order, MUST mark which listed files are present in the current chunk, and MUST include only that chunk's complete diff segments in its unified-diff section. Agentic prompts MUST contain neither chunk context nor a unified-diff section.

#### Scenario: Inline lane reviews the first of two chunks

- **WHEN** the first inline chunk contains `src/a.py` and the second contains `src/b.py`
- **THEN** the first prompt says `chunk 1/2`, lists both paths, marks `src/a.py` as included, and embeds no `src/b.py` diff segment

#### Scenario: Agentic lane reviews both paths

- **WHEN** the agentic range changes `src/a.py` and `src/b.py`
- **THEN** the prompt identifies only the base/head range and the agent discovers both paths from the checkout

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

### Requirement: Discovery requires a reviewable diff

Discovery MUST fail with a machine-readable `empty-review-diff` error containing every excluded file's reason when generated-path and oversized-file exclusions retain zero review characters, and MUST do so before constructing or dispatching runtime work.

#### Scenario: Every changed file is excluded

- **WHEN** all target diff segments match generated paths or exceed the per-file character limit
- **THEN** discovery dispatches no lane replicas and reports the `excluded_reason` mapping instead of producing zero-finding coverage

### Requirement: Lane execution loss degrades the review

Each final invalid planned lane execution MUST identify its lane as failed and MUST retain its replica, chunk, normalized reason, and available diagnostic. A review with at least one valid execution and at least one final invalid execution MUST have status `degraded`; a review with planned executions and no valid execution MUST have status `failed`; only a review with no final invalid planned executions MAY have status `complete`.

#### Scenario: One lane has no output

- **WHEN** one activated lane ends with reason `missing` while another lane returns valid findings
- **THEN** coverage counts only the successful execution as valid, status is `degraded`, and failed-lane detail names the missing-output lane

#### Scenario: Every lane fails

- **WHEN** every activated lane ends with an invalid final execution
- **THEN** status is `failed`, no invalid execution contributes findings, and every lane appears in failed-lane detail

### Requirement: Partial discovery output is preserved

A degraded review MUST preserve and merge findings from valid lane executions, and every machine and human presentation of those findings MUST label the result as partial.

#### Scenario: Valid security lane survives another lane's failure

- **WHEN** a security lane returns usable findings and a correctness lane returns schema-invalid output
- **THEN** the security findings remain in merge and report artifacts under a degraded partial-review status

### Requirement: Discovery explanatory fields obey the configured locale

Every inline, agentic minimal, coverage, and retry discovery prompt MUST require every explanatory field, including title, body, reason, and recommendation, to use the language named by the resolved locale. It MUST instruct the model to preserve identifiers, enum values, paths, symbol names, and quoted source verbatim, and not to follow the language of the diff, PR description, or lane text. Lane text, PR text, and evidence MUST be treated as data rather than language instructions.

#### Scenario: English lane with Korean configuration

- **WHEN** an agentic or retry prompt uses an English lane and locale ko
- **THEN** its output contract explicitly requires Korean explanatory fields while preserving source identifiers
