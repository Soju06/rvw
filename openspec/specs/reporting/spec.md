# reporting

## Purpose

Define durable run artifacts, deterministic report rendering, and bounded GitHub review publication whose event and threads follow repository policy.
## Requirements
### Requirement: Pipeline artifacts are file-first

Every review run MUST create a unique directory under `/tmp/rvw/` by default or use its supplied artifact directory and MUST persist target, discovery, merge, optional adjudication, and report artifacts before publication uses them. Ordinary run identifiers MUST carry a sub-second timestamp component, and default-directory creation MUST resolve a residual run-directory name collision by regenerating the identifier instead of failing, while remaining safe for run-ID validation and reopening. For `run` and `auto`, `--out` MUST select the artifact directory itself and MUST NOT append the run ID.

#### Scenario: PR review completes

- **WHEN** a PR review reaches REPORT with the default output root
- **THEN** its `/tmp/rvw/<run-id>/` directory contains `target.json`, `discover.json`, `merge.json`, optional `outcome.json`, and `report.md`

#### Scenario: Two runs start on the same target in the same second

- **WHEN** two review runs are created for the same pull request within one second
- **THEN** both receive distinct default run directories and neither creation fails

#### Scenario: Adapter supplies a result directory

- **WHEN** `rvw run --out /workspace/result` starts
- **THEN** its artifacts are directly addressable beneath `/workspace/result` without stdout parsing or a copying stage

### Requirement: Run summaries are strict and fail closed

Every review that reaches a terminal state MUST persist and expose a strict run summary containing `status`, `failed_lanes`, coverage totals, and any run-level error. While work is active status MUST be `running`; terminal `status` MUST be exactly `complete`, `degraded`, or `failed`; `rvw review --json` MUST emit the same status and failed-lane detail used by the persisted summary.

#### Scenario: Automation receives partial coverage

- **WHEN** one final lane execution is invalid and another is valid
- **THEN** JSON output and the persisted summary both contain `status: "degraded"` and structured `failed_lanes` rather than presenting the review as complete

### Requirement: Reports disclose incomplete execution

Every degraded or failed run MUST retain each failed lane and every normalized machine-readable reason in diagnostic artifacts. Diagnostic reports MUST disclose partial or failed execution and retain successful findings and coverage counts. The publication view MUST disclose partial or failed execution in localized human prose without publishing lane diagnostics or relabeling invalid executions as valid.

#### Scenario: Missing and malformed lanes coexist

- **WHEN** one lane has missing output and another has unparseable output
- **THEN** `report.md` names both lanes, renders reasons `missing` and `unparseable`, and labels any surviving findings as partial

### Requirement: Report sections are machine-generated except synthesis

The system MUST retain target metadata, finding sections, verdict details, coverage, budget accounting, and generator version in diagnostic artifacts. Diagnostic report sections MUST remain machine-generated except optional synthesis; their headings and placeholders MUST use locale catalogs. An explicit `rvw report --synthesis` file MUST override lane synthesis for report.md. Otherwise validated lane overview and first action MUST supply that section. When neither exists, the diagnostic placeholder MUST be neutral and non-instructional in both locales. Publication MUST NOT publish synthesis instructions.

#### Scenario: No synthesis is supplied

- **WHEN** REPORT renders without an operator file or validated lane synthesis
- **THEN** the synthesis section says “No synthesis was supplied.” in English or “종합이 제공되지 않았습니다.” in Korean and every other section is machine-rendered

#### Scenario: Operator overrides lane synthesis

- **WHEN** both a validated synthesis artifact and --synthesis file exist
- **THEN** report.md uses the operator file and the publication view uses the validated artifact

### Requirement: Reports separate verdict classes

An adjudicated diagnostic report MUST render CONFIRMED groups in the confirmed section, unresolved UNCERTAIN groups in the localized uncertainty section, and REJECTED groups in collapsible details without silently dropping any class.

#### Scenario: Expanded pass remains uncertain

- **WHEN** an outcome lists a group as unresolved
- **THEN** the report includes its finding, votes, reason/evidence when present, and the statement that expanded-context verification remained uncertain

### Requirement: Coverage proves lane participation

Diagnostic artifacts MUST retain a per-lane table of planned dispatched runs, valid runs, findings, and uncovered controller hunk count plus the canonical IDs of any uncovered hunks. Diagnostic report rendering MUST preserve this coverage detail and MUST include kept/excluded diff character accounting and chunk count only when an inline budget report exists.

#### Scenario: One two-chunk inline lane fails entirely

- **WHEN** an activated inline lane has three replicas over two chunks and zero valid outputs
- **THEN** the coverage table contains that lane with `6 / 0 / 0` and the budget summary identifies two chunks rather than making the lane indistinguishable from an omitted lane

#### Scenario: Agentic lane leaves one hunk uncovered

- **WHEN** bounded coverage verification ends with one canonical hunk ID uncovered for a lane
- **THEN** the coverage table gives that lane an uncovered count of one and the report renders the canonical hunk ID without a diff-budget summary

### Requirement: Display folds preserve member detail

Diagnostic report pattern folds MUST render the repeated rule and every member location, region folds MUST contribute adjacency labels, and differing member adjudication reasons MUST render as per-member reason and evidence blocks.

#### Scenario: Pattern members have different reasons

- **WHEN** a four-location pattern fold has non-identical adjudication reasons
- **THEN** the report lists each file and line with its own reason and evidence instead of showing one representative explanation

### Requirement: Publication event follows repository policy

Every GitHub review payload MUST carry the event selected from the repository `publish` policy and the run's PASS/BLOCK verdict: BLOCK maps `on_block` (`comment` → COMMENT, `request_changes` → REQUEST_CHANGES), PASS maps `on_pass` (`comment` → COMMENT, `approve` → APPROVE, `none` → no review when there is nothing to show and COMMENT otherwise). "Something to show" MUST mean at least one non-rejected finding, an unreviewed change region, or an unfinished rule set. The event MUST clamp to COMMENT, with the reason recorded whenever a clamp applies, whenever there is no policy verdict (interactive review), the run has no adjudication outcome, the run summary is `degraded` or `failed` or missing, language fallback was used, rvw's own identity is unknown, a reconciliation read failed, or the policy came from an unverified run snapshot; a clamp MUST also disable dismissal and thread resolution and supersession. Every payload MUST pin `commit_id` to the reviewed head and every body MUST end with the review marker; an APPROVE with nothing to show MUST send the marker as its only body and no inline comments. When the live pull-request head differs from the reviewed head, publication MUST perform no write and record `publication_skipped: head_moved`. Publication MUST never post a second REQUEST_CHANGES for a head on which rvw already has one, and MUST NOT post a same-event review for a head on which rvw already has one when no new inline comment would be posted; both cases MUST record `publication_skipped: duplicate_review_same_head` while thread reconciliation and dismissal still run. On PASS with `dismiss_on_pass: true` and no clamp, publication MUST dismiss rvw's own marked reviews in state `CHANGES_REQUESTED` whose marker names an earlier head with the catalog message (ko `새 커밋에서 통과하여 이전 변경 요청을 해제합니다.`, en `Dismissed: a newer commit passed review.`) through `PUT /repos/{owner}/{repo}/pulls/{number}/reviews/{id}/dismissals`, MUST re-read a review after a rejected dismissal and count it dismissed only when its state is `DISMISSED` (otherwise `dismiss_failed_review_ids`), and MUST never dismiss a review by another identity, an unmarked review, or a review on the current head. The recorded facts MUST include `publish.event`, `publish.policy_source` (`default`, `repository`, or `explicit`), `publish.event_clamped_reason`, `dismissed_review_ids`, and `publication_skipped`.

#### Scenario: Publish payload is built

- **WHEN** the report contains blocker findings and the effective policy has no `publish` block
- **THEN** the GitHub review event remains COMMENT

#### Scenario: Default policy

- **WHEN** a run under a policy without a `publish` block publishes on BLOCK or PASS
- **THEN** the event is COMMENT, as before

#### Scenario: Repository requests changes on BLOCK

- **WHEN** the base policy sets `on_block: request_changes` and a complete run is BLOCK
- **THEN** the review event is REQUEST_CHANGES pinned to the reviewed head, and a rerun on the same head posts no second REQUEST_CHANGES

#### Scenario: Degraded BLOCK

- **WHEN** the same policy applies but the run summary is `degraded`
- **THEN** the event is COMMENT and `event_clamped_reason` is `degraded`

#### Scenario: Nothing to show under on_pass none

- **WHEN** the base policy sets `on_pass: none` and a complete PASS has no finding, uncovered region, or unfinished rule set
- **THEN** no review is posted, `publication_skipped` is `on_pass_none`, and the check run still completes

#### Scenario: Later PASS dismisses an earlier block

- **WHEN** `dismiss_on_pass: true`, the run passes on a newer head, and rvw's own REQUEST_CHANGES exists on an earlier head beside a REQUEST_CHANGES by a human
- **THEN** exactly rvw's review is dismissed with the catalog message and the human's review is untouched

### Requirement: Publication is dry-run by default

The `rvw publish` command MUST write `publish-payload.json` without performing any GitHub write (review creation, thread reply or resolution, review dismissal) unless `--execute` is supplied. A dry run of `rvw publish --run` MAY read the pull request's review threads, reviews, and compare diffs to plan thread reconciliation; those reads are tolerated failures and never abort the dry run. Dry runs of `review` and `gate` MUST perform no GitHub call.

#### Scenario: Operator inspects payload

- **WHEN** an operator runs `rvw publish --run <id>` without `--execute`
- **THEN** the payload and the thread plan are saved under the run directory and no review, reply, resolution, or dismissal is created

#### Scenario: Reads are unavailable during planning

- **WHEN** the dry run cannot read the pull request's threads
- **THEN** the payload is still written with every finding and the plan records `read_failed`

### Requirement: Confirmed anchors become inline comments

Confirmed groups that have a new-side line and `anchorable: true` MUST be emitted as right-side inline comments subject to repository inline policy. Every non-rejected finding MUST also remain in its body section, including findings posted inline. With synthesis, posted-inline findings MUST have a short body entry containing title, source location and consequence while inline items retain the full explanation. Without synthesis the body MUST retain the existing full finding shape. An empty-section message MUST appear only when that section contains zero findings.

The default inline severity floor MUST be suggestion and the default comment cap MUST be null (unlimited). A warning or blocker floor MUST leave lower-severity findings body-only in full. A nonnegative integer cap MUST select highest-severity candidates first, breaking ties by stable finding identity. Living-thread reconciliation MUST use only inline candidates; body-only findings MUST NOT create or maintain threads. Existing `threads.*` controls MUST apply within those candidates. A zero inline cap MUST disable living-thread reconciliation.

#### Scenario: Finding is outside the diff

- **WHEN** a confirmed finding has `anchorable: false`
- **THEN** it remains in the body and is not sent as an inline comment

#### Scenario: Required changes have inline threads

- **WHEN** the summary counts two confirmed blockers posted inline
- **THEN** the body lists both blockers under required changes and does not show an empty-section message there

#### Scenario: Severity and count restrict inline placement

- **WHEN** a repository selects warning and a cap of one for a blocker, warning and suggestion
- **THEN** only the blocker is selected inline, both other findings render in full in the body and their matching existing threads are left untouched

### Requirement: HTTP 422 fallback is bulk and bounded

Publication MUST retry exactly once after a 422 response to a payload containing inline comments by moving every inline item into a localized anchor-fallback body section, and MUST perform at most two GitHub API calls.

#### Scenario: One inline anchor is rejected

- **WHEN** GitHub rejects the initial bulk review with HTTP 422
- **THEN** the second and final call contains no inline comments and places all attempted inline findings in the fallback body section

#### Scenario: Non-422 error occurs

- **WHEN** GitHub returns an error other than 422
- **THEN** publication raises the error without retrying

### Requirement: Gate verdict publication is artifact-derived

The gate MUST generate its verdict from persisted target, discovery, merge, adjudication, coverage, and disposition data, and the persisted verdict JSON MUST contain the run ID, base and head anchors, aggregate verdict counts, per-lane dispatched and valid counts, and each actionable finding's public ID, severity, adjudication verdict, disposition, and reason.

#### Scenario: Later audit reconstructs a gate decision

- **WHEN** a gate verdict contains accepted and must-fix findings across multiple lanes
- **THEN** the saved JSON identifies every decision and the exact anchored run; the localized publication view retains PASS/BLOCK, actionable findings, and disposition reasons while omitting run IDs, actors, and inheritance internals without relying on aggregate counts alone

### Requirement: Gate publication follows the same policy

Gate publication MUST be dry-run by default, MUST use the same policy-selected event construction as ordinary publication with the gate verdict as the policy verdict, and MUST retry at most once without inline comments after an HTTP 422 response without changing the event.

#### Scenario: Gate publication is inspected

- **WHEN** an operator runs gate without `--execute`
- **THEN** rvw writes the payload with the policy-selected event and makes no GitHub write

#### Scenario: Gate inline comment is rejected

- **WHEN** GitHub returns HTTP 422 for the first gate payload containing inline comments
- **THEN** rvw performs one final body-only attempt with the same event and no third request

### Requirement: Stack artifacts are file-first

Every stack run MUST create a unique directory under `/tmp/rvw/` by default or
the supplied output root and MUST persist a strict manifest, incremental member
run references, lineage observations, and a deterministic stack report before
publication uses them.

#### Scenario: Three-member review completes

- **WHEN** every member review, lineage pass, and final anchor check succeeds
- **THEN** the stack run directory contains `stack-manifest.json`,
  `member-runs.json`, `lineage.json`, and `stack-report.md`

### Requirement: Stack reports separate local and tip state

A diagnostic stack report MUST render captured member metadata and ordinary run references,
MUST summarize each member's local finding verdicts, and MUST render every
lineage's origin claim, ordered descendant observations, evidence, and current
`STILL_PRESENT`, `FIXED_IN`, `REGRESSED_IN`, or `UNCERTAIN` state.

The stack publication view MUST use locale catalogs, retain findings, evidence and human disposition reasons, and omit run IDs, actors and inheritance internals.

#### Scenario: Earlier finding is fixed later

- **WHEN** PR 1 contributes a finding that is ABSENT starting at PR 3
- **THEN** PR 1's local section still records the finding and the lineage section
  identifies PR 3 as the fixing member

### Requirement: Stack publication is body-only and dry-run by default

The `stack publish` command MUST write `publish-payload.json` containing a
body-only COMMENT review and the captured tip head SHA as `commit_id`, without a
network call unless `--execute` is supplied. Execute mode MUST make at most one
publication call after successful full-stack anchor revalidation and MUST send
the same commit-pinned payload persisted for inspection.

#### Scenario: Operator inspects a stack payload

- **WHEN** `rvw stack publish --run <id>` is invoked without `--execute`
- **THEN** the saved payload contains `event: COMMENT`, `commit_id` equal to the
  manifest tip head, and the localized stack publication body, contains no inline comments, and
  no GitHub review is created

### Requirement: Policy-gated summaries have one producer

Python MUST emit version-1 `summary.json` with `schema_version: 1`, `lanes` counts `dispatched`, `valid`, `uncovered`, and `uncovered_regions`, `findings` counts for `blocker`, `warning`, and `suggestion`, `verdicts` counts for `CONFIRMED`, `REJECTED`, and `UNCERTAIN`, a `blockers` list of policy-blocking finding identifiers, resolved `presentation` configuration, nullable nonempty-string `publication_failure`, boolean `language_fallback_used`, the `failed_lanes` and `wave_wall_seconds` facts defined by the runtime contract, and common localized `markdown` summary text. `lanes.dispatched` MUST count dispatched lanes, `lanes.valid` MUST count lanes with at least one VALID execution, `lanes.uncovered` MUST count remaining lane-hunk receipts (one per lane and uncovered hunk), and `lanes.uncovered_regions` MUST count distinct uncovered change regions, which is never more than the receipt count. Counts MUST be derived from persisted execution and finding evidence, MUST preserve zero-valid coverage distinctly from clean valid execution, and MUST remain available with partial or missing stage artifacts. Missing execution evidence MUST NOT imply a successful review. App Check summaries and every other presentation of a policy-gated run MUST consume these facts without recounting stage payloads. `outcome.json` MUST retain its adjudication verdict schema and MUST record the per-wave wall telemetry defined by the runtime contract.

The diagnostic `findings` counters MUST retain all merged groups regardless of verdict. Completed human summaries MUST state completion and counts of CONFIRMED blockers and CONFIRMED warnings/suggestions only, plus partial-coverage disclosure counting distinct uncovered change regions and the unfinished rule-set sentence when applicable. Machine execution detail MUST remain in structured artifacts and check `text`, not the human summary.

#### Scenario: Valid execution finds nothing

- **WHEN** one or more discovery lanes are valid and no findings survive
- **THEN** the summary records positive valid coverage and zero finding and verdict counts

#### Scenario: Review never reaches adjudication

- **WHEN** execution fails before adjudication
- **THEN** the summary remains available, the process envelope records failure, and absent verdict evidence is not interpreted as PASS

#### Scenario: Two dead lanes share thirteen regions

- **WHEN** two lanes with zero valid executions each leave the same thirteen hunks uncovered while four lanes are valid
- **THEN** the summary records `lanes.uncovered: 26`, `lanes.uncovered_regions: 13`, both lanes in `failed_lanes`, and a human sentence counting 13 regions

### Requirement: The process manifest enumerates all retained files

The final `process.json` artifact manifest MUST enumerate every regular file written beneath the artifact directory, including top-level contracts, diagnostics, stage files, and nested runtime evidence. Entries MUST use unique output-relative paths and exact final byte sizes, MUST be deterministically sorted, and MUST include `process.json` with its own correct serialized size. Manifest paths MUST NOT traverse outside the artifact directory or name symlinks. Adapters MUST discover retained review artifacts through this manifest instead of an independent hardcoded artifact-name list.

#### Scenario: Runtime evidence is nested

- **WHEN** discovery writes per-replica prompt, schema, output, log, and usage files
- **THEN** the final manifest includes every retained nested file with its output-relative path and actual size

#### Scenario: Adapter uploads a failed review

- **WHEN** review ends before later stage files exist
- **THEN** the manifest lists the files actually retained, and uploading those files does not require absent later-stage artifacts

### Requirement: Renderer chrome uses complete locale catalogs

Every human-facing chrome string in ordinary, publication, gate, and stack renderers MUST come from a locale catalog selected by the resolved presentation snapshot. Korean and English catalogs MUST have identical key sets and compatible declared formatting arguments; formatting each key MUST succeed. Renderer modules MUST contain no Hangul prose literals outside catalogs. Identifiers, enums, paths, and source code MUST remain unchanged.

#### Scenario: English snapshot is rendered

- **WHEN** an existing run with locale en is rendered
- **THEN** all renderer chrome is English and the same keys exist in the Korean catalog

### Requirement: GitHub publication has a separate human view

GitHub review and inline bodies MUST be rendered from persisted finding evidence as a publication view separate from diagnostic `report.md`. The body MUST contain localized outcome, blocker, and warning/suggestion sections, and an uncertainty section only when nonempty. REJECTED findings MUST NOT be published. A full finding item MUST retain its path:line location, localized severity, short code-formatted lane rule ID, human title, impact and correction, and verbatim evidence fence. Partial coverage MUST add a localized sentence stating the number of unreviewed change regions. When any lane has a final INVALID planned execution, the outcome MUST add a localized sentence stating the number of unfinished rule sets followed by their lane identifiers verbatim, joined by `, `, in coverage order. The publication view MUST omit job/run IDs, head/base SHAs, generation timestamps, public finding IDs/group keys, replica agreement and votes, fold diagnostics, coverage tables, diff budgets, coerced-rejection counts, generator/build footers, and synthesis instructions. A configured footer MUST be included. Without synthesis inline comments MUST retain the existing severity/rule, prose and evidence shape. With synthesis they MUST render sentence title, location/severity/rule, what/consequence/fix, collapsed evidence, then the finding marker. A finding posted inline MUST also retain its title/location and consequence in a short synthesized body entry, or its full existing body item without synthesis. A confirmed anchorable finding that reconciliation matched to an existing rvw thread MUST be rendered in the body instead of as an inline comment, so no non-rejected finding disappears from the publication. Existing anchor eligibility and bounded 422 fallback MUST be preserved, with fallback bodies using the same human view.

#### Scenario: Mixed fixture publishes in Korean

- **WHEN** one blocker, two warnings, one rejected finding, one uncertain finding, and one uncovered hunk are rendered with locale ko
- **THEN** the view includes 수정 필요, 확인 필요, the uncertainty section, rule tags, locations and 검토되지 않은 변경 구간이 1곳 있습니다. while excluding rejected findings and diagnostic metadata

#### Scenario: Same fixture publishes in English

- **WHEN** the same evidence is rendered with locale en
- **THEN** the same selected findings and structure use English chrome

#### Scenario: Two lanes did not finish

- **WHEN** `correctness` and `hygiene` end with INVALID final executions and the other lanes are valid
- **THEN** the Korean summary ends with `검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene.` and the English summary with `Rule sets that did not finish: 2 (correctness, hygiene).`, and a review with no failed lane has no such sentence

#### Scenario: Finding already has an open thread

- **WHEN** a confirmed anchorable finding matches an open rvw thread on the new head
- **THEN** it is listed in the review body under its section and no second inline comment is posted

### Requirement: Publication language is checked before every GitHub write

Before any review prose is sent to GitHub, the system MUST split rendered Markdown into prose segments excluding fenced code, inline code, URLs, paths, identifier tokens containing slash, underscore, dot or camelCase, lane identifiers the publication names verbatim, numbers and punctuation. Segments with fewer than 12 letters MUST be skipped. Korean prose MUST have Hangul share of letters at least 0.6; English prose MUST have Latin share at least 0.9 and zero Hangul. Any segment satisfying neither target threshold MUST be a mismatch. On mismatch the system MUST attempt exactly one bounded runtime rewrite receiving only prose segments and returning the same number of segments, then re-render and re-check. Finding count, severity, verdict, path:line anchors, rule tags, and every evidence fence MUST remain byte-identical; a rewrite violating these invariants MUST be rejected. If mismatch remains, no review prose MUST be published and the outcome MUST record `publication_language_mismatch`, unless explicit language fallback permits the original mismatched prose and records `language_fallback_used: true`. Catalog-only localized check outcome summaries MUST remain available.

#### Scenario: Wrong-language finding

- **WHEN** Korean chrome contains an English explanation of at least 12 letters
- **THEN** the gate attempts one rewrite and publishes only if the result satisfies the locale and invariants

#### Scenario: Rewrite changes evidence

- **WHEN** the rewrite changes an evidence fence or segment count
- **THEN** the rewrite is rejected and no prose is published without fallback

#### Scenario: Explicit fallback

- **WHEN** mismatch remains and language fallback is explicitly enabled
- **THEN** mismatched prose may be published and language_fallback_used is true

#### Scenario: Korean summary names Latin lane identifiers

- **WHEN** a Korean publication names the failed lanes `correctness` and `hygiene` verbatim
- **THEN** those identifiers are excluded from prose scoring, the summary passes without a rewrite, and genuinely English prose on the same line is still a mismatch

### Requirement: Findings carry a line-independent identity marker

Every inline review comment rvw publishes MUST end with one HTML comment marker of the form `<!-- rvw:v1 fp=<fingerprint> rule=<rule_id> lane=<lane_id> -->`, where `fingerprint` is the first 16 hexadecimal digits of SHA-256 over `rule_id`, a newline, the path, a newline, and the normalised adjudication evidence, `rule_id` is the finding's rule, and `lane_id` is the first lane of the collapsed group. Normalisation MUST remove quoted line-number prefixes (`path:N:`, `N:`, `N|`, `LN`), collapse whitespace runs, strip trailing punctuation, and drop empty lines; line numbers MUST NOT contribute to the fingerprint. Every review body rvw publishes MUST end with `<!-- rvw:v1 review head=<head sha> event=<EVENT> -->`. The marker builder and parser MUST live in one module with round-trip tests; the parser MUST take the last marker in a body so quoted or injected markers cannot override the appended one. The language gate MUST treat only rvw markers as non-prose and MUST keep scoring every other HTML comment; the rewrite validator MUST reject a replacement that introduces a marker; the 422 fallback body MUST carry inline items without their markers. `report.md` MUST remain unchanged.

#### Scenario: Unrelated edit above the finding

- **WHEN** the same evidence is quoted with different line numbers and different indentation on a later head
- **THEN** the fingerprint is identical, while a change to the quoted evidence, the rule, or the path changes it

#### Scenario: Korean inline comment carries the marker

- **WHEN** a Korean inline body ends with the marker
- **THEN** the language gate passes without a rewrite and the marker is not among the prose segments

#### Scenario: Quoted marker in evidence

- **WHEN** an inline body contains an rvw-shaped marker inside its evidence fence and rvw's own marker last
- **THEN** the parser returns rvw's marker

### Requirement: rvw's own review threads are reconciled across heads

When publication executes with a known own identity, or when `rvw publish --run` plans a dry run, rvw MUST read every review thread of the pull request through GraphQL `pullRequest.reviewThreads` with cursor pagination, MUST treat as its own only threads whose first comment carries a marker and whose author matches its identity (GraphQL `login` equal to the bare slug with `__typename` `Bot` for an App, `User` otherwise), and MUST record any other thread as foreign. A thread with a comment by another identity MUST count as human-engaged. Matching against the run's non-rejected findings MUST proceed in order: an exact fingerprint on the same path when that fingerprint is unique among rvw's open threads (a resolved thread matches only when no open thread carries it) and among findings on the path; otherwise, within the same `rule_id` and path, a live thread's GitHub-tracked `line` or an outdated thread's `originalLine` mapped through the hunks of the diff from the thread's original commit to the new head (local `git diff` with external drivers, colour, and prefix settings disabled when both commits exist, otherwise the compare API accepted only when its merge base is the original commit, with file headers synthesised in front of the header-less patch; a path absent from the compare list MUST be unavailable, never unchanged) landing on a finding's line; otherwise exactly one remaining thread and one remaining finding for that pair. Two threads claiming one finding, or two or more unmappable threads beside remaining findings, MUST be ambiguous.

Outcomes MUST be: `reused` for a matched open thread, whose finding MUST NOT be posted inline again and MUST remain in the review body; `superseded` for a matched outdated thread whose finding is inline-capable when no clamp, `threads.resolve_on_fix: false`, or human reply withholds the supersession (otherwise the thread is `reused` and the finding is not posted inline again), which MUST be posted again at its current line and, only after that comment was actually posted inline, replied to with the catalog text (ko `같은 발견이 새 위치에서 계속됩니다: {path}:{line}`, en `Same finding continues at {path}:{line}`) and resolved; `skipped_resolved` for a thread already resolved, which MUST never be touched and, when matched, MUST suppress the inline repost; `ambiguous`, which MUST leave the threads open and post none of the pair's findings inline. An unmatched open thread MUST be resolved through `resolveReviewThread` with resolution reason `ADDRESSED`, without a reply, only when all of the following hold, otherwise it MUST stay open with the first applicable reason recorded: the run is not clamped (`skipped_degraded`); the thread was not created on the current head (`skipped_same_head`); no other identity commented (`skipped_human_reply`); the marker's lane has at least one VALID execution on the new head (`skipped_lane_invalid`); the thread is outdated, its original line was deleted or edited, or its path is no longer in the pull-request diff and was not renamed by it, and its position could be mapped when the path is still in the diff (`skipped_unverified`); its path is not budget-excluded and its mapped line's hunk is not in the lane's uncovered list (`skipped_uncovered`); `threads.resolve_on_fix` is true (`skipped_policy`). Resolution and supersession MUST happen only after the review write succeeded and MUST never fail the publication: a thread MUST count as resolved only when GitHub reports it resolved; a `FORBIDDEN` GraphQL error MUST stop further writes; a `NOT_FOUND` error MUST count the thread as missing; any other write failure MUST record the thread under `threads_skipped_write_failed` with reason `write_failed` and continue; the recorded facts MUST be persisted even when a later write fails. `threads.reuse_open_thread: false` MUST post every finding and leave matched threads untouched. A failed or truncated read MUST clamp: no resolution, no supersession, every finding posted, reason `read_failed` recorded. Threads published before markers existed MUST never be touched.

#### Scenario: Author fixes one finding and keeps another

- **WHEN** the new head deletes the flagged line of one thread whose lane is valid and leaves another finding with the same fingerprint
- **THEN** the review posts the surviving finding only in its body, resolves the first thread after the review is created, and records both thread ids

#### Scenario: Finding continues at a new line

- **WHEN** an outdated rvw thread's fingerprint matches a finding at a different line
- **THEN** the review posts that finding inline at the new line, replies to the old thread with the catalog sentence, and resolves it

#### Scenario: Lane died on the new head

- **WHEN** an unmatched thread's lane has zero VALID executions on the new head
- **THEN** the thread stays open and `threads_skipped_lane_invalid` names it

#### Scenario: Live thread whose finding was not re-reported

- **WHEN** a non-outdated thread has no matching finding and its region did not change
- **THEN** the thread stays open with reason `skipped_unverified`

#### Scenario: Two threads share a rule and path

- **WHEN** two unmatched outdated threads for one `rule_id` and path cannot be mapped and a finding for that pair exists
- **THEN** both stay open, the finding is not posted inline, and `threads_ambiguous` names both

#### Scenario: Author already resolved the thread

- **WHEN** a matched rvw thread is already resolved
- **THEN** it is left untouched, the finding is not posted inline, and `threads_skipped_resolved` names it

#### Scenario: Inline anchors are rejected

- **WHEN** GitHub returns 422 and the review falls back to a body-only publication
- **THEN** fixed threads are still resolved, outdated threads are left open as reused, and the fallback body carries no marker

#### Scenario: Degraded run

- **WHEN** the run summary is `degraded` or `failed`, or language fallback was used
- **THEN** matched threads are reused, no thread is resolved or superseded, and `threads_skipped_reason` is `degraded`

### Requirement: Publication records what it did to threads

`summary.json` MUST carry a strict `publish` object with `event`, `policy_source`, `actor` (rvw's REST login or null), `event_clamped_reason`, `dismissed_review_ids`, `dismiss_failed_review_ids`, `resolved_thread_ids`, `reused_thread_ids`, `superseded_thread_ids`, `threads_ambiguous`, `threads_skipped_lane_invalid`, `threads_skipped_resolved`, `threads_skipped_same_head`, `threads_skipped_human_reply`, `threads_skipped_unverified`, `threads_skipped_uncovered`, `threads_skipped_missing`, `threads_skipped_write_failed`, and `threads_skipped_reason` (`login_unknown`, `read_failed`, `degraded`, `forbidden`, `write_failed`, `disabled_by_policy`, or `not_planned`), and a nullable `publication_skipped`. Publication MUST persist these after its last GitHub operation. A dry run MUST write the planned resolves, supersessions, reuses, and suppressed inline findings under `plan` in `publish-payload.json` when it planned threads. Legacy summaries without these fields MUST load with defaults in Python and in the App parser, and the App check `text` MUST carry `publish` and `publication_skipped` verbatim from the summary without touching the summary sentence.

#### Scenario: Reconciliation performed

- **WHEN** publication resolves one thread, supersedes one, and reuses one
- **THEN** `summary.json` lists each id under its outcome and `actor` names rvw's login

#### Scenario: Identity unknown

- **WHEN** neither `RVW_GITHUB_LOGIN` nor the token's user identifies rvw
- **THEN** no thread is read or touched, every finding is posted, and `threads_skipped_reason` is `login_unknown`

### Requirement: Synthesized publication leads with purpose and consequences

When validated synthesis exists, the body MUST open with overview followed by non-null first_action in the opening paragraph. The catalog outcome and coverage/failure disclosure MUST follow as the second paragraph, with degraded/incomplete disclosure retained. Full finding items MUST render sentence title, path/line, localized severity and rule, what, consequence and fix, followed by persisted evidence in details with a localized summary. The human view MUST retain synthesis finding order within each authoritative severity/verdict section and MUST omit adjudication reason when synthesis exists. Diagnostic reports MUST retain it. Synthesis MUST pass the existing publication language gate with source paths, identifiers and code spans protected; the rewrite path and terminal marker positions MUST remain unchanged.

#### Scenario: Synthesized Korean inline item

- **WHEN** a Korean synthesis contains English source identifiers and evidence
- **THEN** the body and inline both contain the finding, the language gate preserves literals, evidence is collapsed and the inline marker remains last

### Requirement: Presentation includes repository reviewer voice

Repository `.rvw/config.yaml` MUST accept an optional strict voice mapping with audience `engineers|mixed` defaulting to engineers, register `formal|neutral` defaulting to formal, and optional string guidance of at most 800 Unicode characters. Unknown keys, invalid values and oversized guidance MUST fail closed with `presentation_config_invalid`. Voice MUST affect presentation only and MUST be retained in presentation snapshots with defaults for legacy snapshots.

#### Scenario: Invalid voice configuration

- **WHEN** voice has an unknown audience or guidance longer than 800 characters
- **THEN** configuration is rejected before runtime execution

### Requirement: Publication controls are persisted as facts

Summary publish facts MUST include resolved channels and inline_policy containing severity_at_least, max_comments and body_only_count. Missing legacy fields MUST load with defaults. An absent review channel MUST prevent all review, comment and thread writes, even with an explicit publication request. Non-inline findings MUST render in full in the review body.

#### Scenario: Suggestions stay body-only

- **WHEN** the repository sets the warning floor and review includes one confirmed suggestion and one anchorable warning
- **THEN** only the warning is an inline candidate, the suggestion remains fully explained in the body, and body_only_count includes the suggestion
