# discovery

## Purpose

Define target preparation, gap-coverage prompting, replicated dispatch, dynamic-brief fallback, and bounded diff handling for the DISCOVER stage.

## Requirements

### Requirement: The unscoped sweep is an always-active base lane

The runtime registry MUST register `unscoped-sweep` in a predicate-free base layer, and its lane schema MUST cap emitted severity at `warning`.

#### Scenario: Project has many scoped lanes

- **WHEN** a target activates project, scope, and dynamic lanes
- **THEN** `unscoped-sweep` is still dispatched and cannot emit a blocker-severity finding

### Requirement: Uncommitted targets expand untracked directories safely

An uncommitted target MUST obtain untracked paths from Git with the repository's
standard exclusion rules, then include only sorted regular non-symlink files
beneath the worktree. Each included member MUST appear in `changed_paths` and
be rendered through the ordinary untracked-file diff path. The resolver MUST
not read a directory as a text file, follow symlinks outside the worktree, or
include ignored files in the review diff.

#### Scenario: OpenSpec archive directory is untracked

- **WHEN** Git status reports an untracked directory containing Markdown files
- **THEN** the uncommitted target includes each non-ignored Markdown file in its
  diff and changed paths without raising `IsADirectoryError`

#### Scenario: Untracked directory contains ignored credentials

- **WHEN** an untracked directory contains a regular source file and an ignored
  `.env` file
- **THEN** the source file is included and the ignored `.env` contents and path
  are absent from the target diff and changed paths

### Requirement: Sweep prompts receive covered rules

A lane declaring `covered_by_others: inject` MUST receive every other active lane's rule IDs in an already-covered section and MUST be instructed not to re-report those classes.

#### Scenario: Two other lanes are active

- **WHEN** the sweep runs beside security and schema lanes
- **THEN** its prompt names both lanes and their rule IDs as already covered

### Requirement: Discovery uses only planned evidence by default

Every default discovery execution MUST receive a tool-less runtime and MUST
treat its lane prompt, dynamic brief, declared rules, and planned diff chunk as
its complete evidence boundary. It MUST not invoke shell, browser, app,
computer, plugin, image, or multi-agent tools. A claim that cannot be supported
by this evidence MUST not become a finding.

#### Scenario: Lane needs an unchanged caller

- **WHEN** a discovery lane cannot establish a defect from the supplied diff
  chunk and prompt evidence alone
- **THEN** it returns no finding rather than searching the repository

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

- **WHEN** discovery uses its default replica count while adjudication uses three replicas
- **THEN** discovery submits eight planned runs without waiting for one lane or chunk to finish before submitting another

#### Scenario: Three replicas are explicitly requested

- **WHEN** discovery is called with three replicas for four active lanes over two chunks
- **THEN** it submits 24 planned runs through the existing shared wave regardless of the adjudication replica count

#### Scenario: Preflight and dispatch share a plan

- **WHEN** a target activates four lanes with three discovery replicas over one
  chunk
- **THEN** preflight reports 12 initial runs, 24 retry-upper-bound runs, and
  the exact sum of the twelve prompts that dispatch will send

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

An invalid replica MUST be excluded from finding enrichment. A lane-chunk group
MUST receive exactly one replacement wave only when every initial replica is
INVALID and every invalid reason is `unparseable` or
`schema-invalid`; an initial wave MUST NOT contain retry feedback. A
timeout, cancellation, budget, spawn, completion-marker, missing-artifact, or
other invalid reason MUST NOT cause an identical full-wave retry. Any lane-chunk
group with no valid result after its permitted retry decision MUST retain its
final INVALID executions for run-level failure evaluation rather than
contributing a zero-finding PASS.
Replacement artifacts and ordered attempt coverage retain the existing contract,
and legacy discovery artifacts continue to load with empty attempt history.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID with
  correctable schema or format reasons
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and
  performs no further retry

#### Scenario: Replacement prompt names correctable prior failures

- **WHEN** every initial replica of one lane-chunk is INVALID with an
  `unparseable` or `schema-invalid` reason
- **THEN** that lane-chunk's replacement prompt lists each prior replica's
  invalid reason while another lane's unretried prompt contains none

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

#### Scenario: Retried coverage keeps the initial failure reason

- **WHEN** a lane-chunk retried after an initial `schema-invalid` result succeeds in the replacement wave
- **THEN** its persisted coverage row is valid, and its attempt records list the initial INVALID attempt with reason `schema-invalid` followed by the valid retry attempt

#### Scenario: Legacy discovery artifact loads

- **WHEN** a `discover.json` persisted before attempt records is loaded
- **THEN** loading succeeds and each coverage run reports empty attempt history

### Requirement: Compatible discovery resume preserves attempts

Discovery resume MUST persist the exact discovery plan, execution settings, and
each completed result before continuing. `rvw run --run <id>` MUST reuse only
the persisted plan's lane, replica, and chunk identities, retain each identity's
ordered attempt history, must not dispatch a third attempt, and MUST write any
new resumed execution to an artifact directory distinct from prior attempts.

#### Scenario: Interrupted review reuses persisted valid work

- **WHEN** a review is interrupted after a valid lane-replica-chunk completes
- **THEN** `rvw run --run <id>` retains that result without dispatching it again

#### Scenario: Resume keeps the original planned prompt

- **WHEN** a review is interrupted and the lane registry or operator brief later changes
- **THEN** `rvw run --run <id>` continues with the persisted plan rather than mixing results from a newly built prompt

#### Scenario: Resume preserves a partially completed replacement wave

- **WHEN** compatible history records correctable initial failures and a
  replacement result for only some replicas
- **THEN** discovery dispatches only the missing replacement replicas and keeps
  their attempt numbering and artifacts distinct

### Requirement: Dynamic brief falls back to PR claims

Dynamic lanes MUST use an operator-supplied brief when present, SHALL otherwise
use the PR title and body when available, and MUST label the PR-derived brief
as an UNVERIFIED claim of intent. A dynamic lane declaring `requires_brief:
true` with neither source MUST not invoke a runtime and MUST record zero
dispatch with `skipped_reason: brief_unavailable`.

#### Scenario: No operator brief for a PR

- **WHEN** a PR target has a title and body but no `--dynamic-brief`
- **THEN** dynamic prompts contain the title/body and the UNVERIFIED note

#### Scenario: No brief source exists

- **WHEN** a commit target has no operator brief and a dynamic lane does not
  require one
- **THEN** dynamic prompts state that the brief is unavailable and findings should be marked inconclusive

#### Scenario: No brief source exists for a required lane

- **WHEN** a commit target has no operator brief and an activated dynamic lane
  declares `requires_brief: true`
- **THEN** that lane is recorded as skipped for `brief_unavailable` and makes
  no model call

### Requirement: Generated and oversized files are visibly excluded

Discovery MUST exclude default generated globs (`**/runtime-snapshots/**`, `**/*.generated.*`, `**/generated/**`, lockfiles, `**/dist/**`, and `**/__snapshots__/**`) and per-file diffs above 200,000 characters, MUST retain exact kept/excluded character accounting, and MUST prepend a visible exclusion header to the review diff.

#### Scenario: Generated snapshot dominates a diff

- **WHEN** a generated snapshot matches a configured glob
- **THEN** it is absent from lane diff content, appears in the exclusion report with reason `generated-path`, and is named in the visible header

### Requirement: Diff budget plans ordered file chunks

After generated-path and oversized-file exclusions, discovery MUST partition complete kept file segments with order-preserving greedy next-fit packing, MUST place every kept file in exactly one chunk, and MUST keep each chunk's retained segment characters at or below 400,000. The planner MUST return one chunk when the retained diff fits, MUST preserve that filtered diff byte-for-byte, and MUST record ordered chunk count, file placement, and character accounting. The same module MUST additionally expose an unpartitioned reviewed-diff projection that returns the concatenated kept segments behind the visible exclusion header together with the same exclusion report, so post-discovery stages apply one shared exclusion policy rather than re-implementing it.

#### Scenario: Ordinary diff fits one chunk

- **WHEN** retained file segments total at most 400,000 characters
- **THEN** the planner returns one chunk whose diff bytes equal the previously filtered result

#### Scenario: Large source diff requires multiple chunks

- **WHEN** retained file segments total about 735,000 characters and every file is at most 200,000 characters
- **THEN** the planner returns at least two chunks in source order, every chunk is at most 400,000 retained characters, and every kept file appears exactly once

#### Scenario: A post-discovery stage requests the reviewed diff

- **WHEN** a caller requests the reviewed-diff projection for a target whose diff contains one generated file and one kept file
- **THEN** it receives the kept segment behind the exclusion header plus the exclusion report, and the generated segment is absent

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
