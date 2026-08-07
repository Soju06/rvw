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

A lane declaring `covered_by_others: inject` MUST receive every other active lane's rule IDs in an already-covered section and MUST be instructed not to re-report those classes.

#### Scenario: Two other lanes are active

- **WHEN** the sweep runs beside security and schema lanes
- **THEN** its prompt names both lanes and their rule IDs as already covered

### Requirement: Discovery dispatch defaults to one replica

The DISCOVER stage MUST plan one run per active lane per diff chunk by default and MUST dispatch all lane-replica-chunk runs through one shared wave. It MUST preserve the requested count when callers explicitly request multiple replicas.

#### Scenario: Four lanes activate over two chunks

- **WHEN** discovery uses the default replica count
- **THEN** it submits eight planned runs without waiting for one lane or chunk to finish before submitting another

#### Scenario: Three replicas are explicitly requested

- **WHEN** discovery is called with three replicas for four active lanes over two chunks
- **THEN** it submits 24 planned runs through the existing shared wave

### Requirement: Dispatch is bounded and heavy-first

The dispatcher MUST sort runs heavy, normal, then light, MUST bound concurrent runtime executions with a semaphore whose default capacity is 8, and MUST preserve an explicitly requested positive capacity.

#### Scenario: Heavy and light lanes share a plan

- **WHEN** semaphore capacity becomes available at the start of a wave
- **THEN** heavy lane runs are queued before normal and light lane runs while in-flight work never exceeds 8 by default

#### Scenario: Caller overrides concurrency

- **WHEN** discovery is called with concurrency 3
- **THEN** in-flight runtime executions never exceed 3

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment, and the dispatcher MUST retry a lane-chunk group exactly once only when every initial replica for that lane and chunk is INVALID. The replacement wave MUST persist its artifacts in a run directory distinct from the initial wave's so the initial INVALID artifacts remain inspectable, while the directory's final component preserves the runtime replica-derivation contract.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and performs no further retry

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

### Requirement: Dynamic brief falls back to PR claims

Dynamic lanes MUST use an operator-supplied brief when present, SHALL otherwise use the PR title and body when available, and MUST label the PR-derived brief as an UNVERIFIED claim of intent.

#### Scenario: No operator brief for a PR

- **WHEN** a PR target has a title and body but no `--dynamic-brief`
- **THEN** dynamic prompts contain the title/body and the UNVERIFIED note

#### Scenario: No brief source exists

- **WHEN** a commit target has no operator brief
- **THEN** dynamic prompts state that the brief is unavailable and findings should be marked inconclusive

### Requirement: Generated and oversized files are visibly excluded

Discovery MUST exclude default generated globs (`**/runtime-snapshots/**`, `**/*.generated.*`, `**/generated/**`, lockfiles, `**/dist/**`, and `**/__snapshots__/**`) and per-file diffs above 200,000 characters, MUST retain exact kept/excluded character accounting, and MUST prepend a visible exclusion header to the review diff.

#### Scenario: Generated snapshot dominates a diff

- **WHEN** a generated snapshot matches a configured glob
- **THEN** it is absent from lane diff content, appears in the exclusion report with reason `generated-path`, and is named in the visible header

### Requirement: Diff budget plans ordered file chunks

After generated-path and oversized-file exclusions, discovery MUST partition complete kept file segments with order-preserving greedy next-fit packing, MUST place every kept file in exactly one chunk, and MUST keep each chunk's retained segment characters at or below 400,000. The planner MUST return one chunk when the retained diff fits, MUST preserve that filtered diff byte-for-byte, and MUST record ordered chunk count, file placement, and character accounting.

#### Scenario: Ordinary diff fits one chunk

- **WHEN** retained file segments total at most 400,000 characters
- **THEN** the planner returns one chunk whose diff bytes equal the previously filtered result

#### Scenario: Large source diff requires multiple chunks

- **WHEN** retained file segments total about 735,000 characters and every file is at most 200,000 characters
- **THEN** the planner returns at least two chunks in source order, every chunk is at most 400,000 retained characters, and every kept file appears exactly once

### Requirement: Chunk prompts expose the whole file plan

Every discovery prompt MUST identify its `chunk k/N`, MUST list every kept file path in source order, MUST mark which listed files are present in the current chunk, and MUST include only that chunk's complete diff segments in its unified-diff section.

#### Scenario: Lane reviews the first of two chunks

- **WHEN** the first chunk contains `src/a.py` and the second contains `src/b.py`
- **THEN** the first prompt says `chunk 1/2`, lists both paths, marks `src/a.py` as included, and embeds no `src/b.py` diff segment

### Requirement: Discovery records per-lane coverage

Discovery MUST record each activated lane's aggregate dispatched, valid, and finding counts and MUST record exactly one strict run entry for every planned `(replica, chunk)` combination, including entries with zero findings or INVALID results and their machine-readable invalid reasons.

#### Scenario: One chunk remains invalid

- **WHEN** a two-chunk, three-replica lane has five VALID final results and one INVALID final result
- **THEN** coverage reports six dispatched, five valid, and six distinct run entries identifying the invalid replica-chunk combination
