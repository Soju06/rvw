## RENAMED Requirements

- FROM: `### Requirement: Publication is COMMENT-only`
- TO: `### Requirement: Publication event follows repository policy`

- FROM: `### Requirement: Gate publication preserves COMMENT safety`
- TO: `### Requirement: Gate publication follows the same policy`

## ADDED Requirements

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

When publication executes with a known own identity, or when `rvw publish --run` plans a dry run, rvw MUST read every review thread of the pull request through GraphQL `pullRequest.reviewThreads` with cursor pagination, MUST treat as its own only threads whose first comment carries a marker and whose author matches its identity (GraphQL `login` equal to the bare slug with `__typename` `Bot` for an App, `User` otherwise), and MUST record any other thread as foreign. A thread with a comment by another identity MUST count as human-engaged. Matching against the run's non-rejected findings MUST proceed in order: an exact fingerprint on the same path when that fingerprint is unique among rvw's threads and among findings on the path; otherwise, within the same `rule_id` and path, a live thread's GitHub-tracked `line` or an outdated thread's `originalLine` mapped through the hunks of the diff from the thread's original commit to the new head (local `git diff` when both commits exist, otherwise the compare API accepted only when its merge base is the original commit, with file headers synthesised in front of the header-less patch) landing on a finding's line; otherwise exactly one remaining thread and one remaining finding for that pair. Two threads claiming one finding, or two or more unmappable threads beside remaining findings, MUST be ambiguous.

Outcomes MUST be: `reused` for a matched open thread, whose finding MUST NOT be posted inline again and MUST remain in the review body; `superseded` for a matched outdated thread whose finding is inline-capable, which MUST be posted again at its current line and, only after that comment was actually posted inline, replied to with the catalog text (ko `같은 발견이 새 위치에서 계속됩니다: {path}:{line}`, en `Same finding continues at {path}:{line}`) and resolved; `skipped_resolved` for a thread already resolved, which MUST never be touched and, when matched, MUST suppress the inline repost; `ambiguous`, which MUST leave the threads open and post none of the pair's findings inline. An unmatched open thread MUST be resolved through `resolveReviewThread` with resolution reason `ADDRESSED`, without a reply, only when all of the following hold, otherwise it MUST stay open with the first applicable reason recorded: the run is not clamped (`skipped_degraded`); the thread was not created on the current head (`skipped_same_head`); no other identity commented (`skipped_human_reply`); the marker's lane has at least one VALID execution on the new head (`skipped_lane_invalid`); the thread is outdated, its original line was deleted or edited, or its path is no longer in the pull-request diff, and its position could be mapped when the path is still in the diff (`skipped_unverified`); its path is not budget-excluded and its mapped line's hunk is not in the lane's uncovered list (`skipped_uncovered`); `threads.resolve_on_fix` is true (`skipped_policy`). Resolution and supersession MUST happen only after the review write succeeded; a thread MUST count as resolved only when GitHub reports it resolved; a `FORBIDDEN` GraphQL error MUST stop further writes and a `NOT_FOUND` error MUST count the thread as missing. `threads.reuse_open_thread: false` MUST post every finding and leave matched threads untouched. A failed or truncated read MUST clamp: no resolution, no supersession, every finding posted, reason `read_failed` recorded. Threads published before markers existed MUST never be touched.

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

`summary.json` MUST carry a strict `publish` object with `event`, `policy_source`, `actor` (rvw's REST login or null), `event_clamped_reason`, `dismissed_review_ids`, `dismiss_failed_review_ids`, `resolved_thread_ids`, `reused_thread_ids`, `superseded_thread_ids`, `threads_ambiguous`, `threads_skipped_lane_invalid`, `threads_skipped_resolved`, `threads_skipped_same_head`, `threads_skipped_human_reply`, `threads_skipped_unverified`, `threads_skipped_uncovered`, `threads_skipped_missing`, and `threads_skipped_reason` (`login_unknown`, `read_failed`, `degraded`, `forbidden`, `disabled_by_policy`, or `not_planned`), and a nullable `publication_skipped`. Publication MUST persist these after its last GitHub operation. A dry run MUST write the planned resolves, supersessions, reuses, and suppressed inline findings under `plan` in `publish-payload.json` when it planned threads. Legacy summaries without these fields MUST load with defaults in Python and in the App parser.

#### Scenario: Reconciliation performed

- **WHEN** publication resolves one thread, supersedes one, and reuses one
- **THEN** `summary.json` lists each id under its outcome and `actor` names rvw's login

#### Scenario: Identity unknown

- **WHEN** neither `RVW_GITHUB_LOGIN` nor the token's user identifies rvw
- **THEN** no thread is read or touched, every finding is posted, and `threads_skipped_reason` is `login_unknown`

## MODIFIED Requirements

### Requirement: Publication event follows repository policy

Every GitHub review payload MUST carry the event selected from the repository `publish` policy and the run's PASS/BLOCK verdict: BLOCK maps `on_block` (`comment` → COMMENT, `request_changes` → REQUEST_CHANGES), PASS maps `on_pass` (`comment` → COMMENT, `approve` → APPROVE, `none` → no review when there is nothing to show and COMMENT otherwise). "Something to show" MUST mean at least one non-rejected finding, an unreviewed change region, or an unfinished rule set. The event MUST clamp to COMMENT, with the reason recorded, whenever there is no policy verdict (interactive review), the run summary is `degraded` or `failed` or missing, language fallback was used, rvw's own identity is unknown, a reconciliation read failed, or the policy came from an unverified run snapshot; a clamp MUST also disable dismissal and thread resolution. Every payload MUST pin `commit_id` to the reviewed head and every body MUST end with the review marker; an APPROVE with nothing to show MUST send the marker as its only body and no inline comments. When the live pull-request head differs from the reviewed head, publication MUST perform no write and record `publication_skipped: head_moved`. Publication MUST never post a second REQUEST_CHANGES for a head on which rvw already has one, and MUST NOT post a same-event review for a head on which rvw already has one when no new inline comment would be posted; both cases MUST record `publication_skipped: duplicate_review_same_head` while thread reconciliation and dismissal still run. On PASS with `dismiss_on_pass: true` and no clamp, publication MUST dismiss rvw's own marked reviews in state `CHANGES_REQUESTED` whose marker names an earlier head with the catalog message (ko `새 커밋에서 통과하여 이전 변경 요청을 해제합니다.`, en `Dismissed: a newer commit passed review.`) through `PUT /repos/{owner}/{repo}/pulls/{number}/reviews/{id}/dismissals`, MUST re-read a review after a rejected dismissal and count it dismissed only when its state is `DISMISSED` (otherwise `dismiss_failed_review_ids`), and MUST never dismiss a review by another identity, an unmarked review, or a review on the current head. The recorded facts MUST include `publish.event`, `publish.policy_source` (`default`, `repository`, or `explicit`), `publish.event_clamped_reason`, `dismissed_review_ids`, and `publication_skipped`.

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

### Requirement: Gate publication follows the same policy

Gate publication MUST be dry-run by default, MUST use the same policy-selected event construction as ordinary publication with the gate verdict as the policy verdict, and MUST retry at most once without inline comments after an HTTP 422 response without changing the event.

#### Scenario: Gate publication is inspected

- **WHEN** an operator runs gate without `--execute`
- **THEN** rvw writes the payload with the policy-selected event and makes no GitHub write

#### Scenario: Gate inline comment is rejected

- **WHEN** GitHub returns HTTP 422 for the first gate payload containing inline comments
- **THEN** rvw performs one final body-only attempt with the same event and no third request

### Requirement: GitHub publication has a separate human view

GitHub review and inline bodies MUST be rendered from persisted finding evidence as a publication view separate from diagnostic `report.md`. The body MUST contain localized outcome, blocker, and warning/suggestion sections, and an uncertainty section only when nonempty. REJECTED findings MUST NOT be published. A finding MUST retain its path:line location, localized severity, short code-formatted lane rule ID, human title, impact and correction, and verbatim evidence fence. Partial coverage MUST add a localized sentence stating the number of unreviewed change regions. When any lane has a final INVALID planned execution, the outcome MUST add a localized sentence stating the number of unfinished rule sets followed by their lane identifiers verbatim, joined by `, `, in coverage order. The publication view MUST omit job/run IDs, head/base SHAs, generation timestamps, public finding IDs/group keys, replica agreement and votes, fold diagnostics, coverage tables, diff budgets, coerced-rejection counts, generator/build footers, and synthesis instructions. A configured footer MUST be included. Inline comments MUST render severity and rule tag, title, impact/correction, then evidence, then the finding marker. A confirmed anchorable finding that reconciliation matched to an existing rvw thread MUST be rendered in the body instead of as an inline comment, so no non-rejected finding disappears from the publication. Existing anchor eligibility and bounded 422 fallback MUST be preserved, with fallback bodies using the same human view.

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
