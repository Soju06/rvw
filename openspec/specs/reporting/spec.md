# reporting

## Purpose

Define durable run artifacts, deterministic report rendering, and bounded GitHub COMMENT publication.
## Requirements
### Requirement: Pipeline artifacts are file-first

Every review run MUST create a unique directory under `/tmp/rvw/` by default or the supplied output root and MUST persist target, discovery, merge, optional adjudication, and report artifacts before publication uses them. Ordinary run identifiers MUST carry a sub-second timestamp component, and creation MUST resolve a residual run-directory name collision by regenerating the identifier instead of failing, while remaining safe for run-ID validation and reopening.

#### Scenario: PR review completes

- **WHEN** a PR review reaches REPORT with the default output root
- **THEN** its `/tmp/rvw/<run-id>/` directory contains `target.json`, `discover.json`, `merge.json`, optional `outcome.json`, and `report.md`

#### Scenario: Two runs start on the same target in the same second

- **WHEN** two review runs are created for the same pull request within one second
- **THEN** both receive distinct run directories and neither creation fails

### Requirement: Run summaries are strict and fail closed

Every review that reaches a terminal state MUST persist and expose a strict run summary containing `status`, `failed_lanes`, coverage totals, and any run-level error. While work is active status MUST be `running`; terminal `status` MUST be exactly `complete`, `degraded`, or `failed`; `rvw review --json` MUST emit the same status and failed-lane detail used by the persisted summary.

#### Scenario: Automation receives partial coverage

- **WHEN** one final lane execution is invalid and another is valid
- **THEN** JSON output and the persisted summary both contain `status: "degraded"` and structured `failed_lanes` rather than presenting the review as complete

### Requirement: Reports disclose incomplete execution

Every report for a degraded or failed run MUST state prominently that the review is partial or failed and MUST list each failed lane with every normalized machine-readable reason. The report MUST retain successful findings and ordinary coverage counts without relabeling invalid executions as valid.

#### Scenario: Missing and malformed lanes coexist

- **WHEN** one lane has missing output and another has unparseable output
- **THEN** `report.md` names both lanes, renders reasons `missing` and `unparseable`, and labels any surviving findings as partial

### Requirement: Report sections are machine-generated except synthesis

The report renderer MUST machine-generate target metadata, finding sections, verdict details, coverage, budget accounting, and generator version, while only the `## 종합` content MAY be supplied as free-form synthesis.

#### Scenario: No synthesis is supplied

- **WHEN** REPORT renders without `--synthesis`
- **THEN** `## 종합` contains the orchestrator placeholder and every other section is machine-rendered

### Requirement: Finding agreement discloses discovery coverage

Every machine-rendered finding agreement MUST use the distinct discovery replica count as its numerator and the run's configured discovery replica count as its denominator. Ordinary report items, pattern-fold items, inline publication comments, retained body items, and HTTP 422 fallback items MUST use the same denominator and MUST NOT derive it from adjudication votes. Runs whose persisted discovery artifacts predate denominator derivation support MAY retain the historical denominator when exact discovery coverage is unavailable.

#### Scenario: Single-replica report is rendered

- **WHEN** a run configured with one discovery replica renders an ordinary finding with agreement one
- **THEN** the report states `복제 동의 1/1` regardless of the number of adjudication votes

#### Scenario: Two-replica pattern is rendered

- **WHEN** a run configured with two discovery replicas renders a pattern-fold item whose highest-priority member has agreement one
- **THEN** the pattern item states `복제 동의 1/2`

#### Scenario: Publication rerenders a finding item

- **WHEN** publication builds an inline comment or HTTP 422 body fallback from a run configured with one discovery replica
- **THEN** every rerendered finding item states `/1` and no rerendered item states `/3`

### Requirement: Reports separate verdict classes

An adjudicated report MUST render CONFIRMED groups in the confirmed section, unresolved UNCERTAIN groups in `## 검증 미확정`, and REJECTED groups in collapsible details without silently dropping any class.

#### Scenario: Expanded pass remains uncertain

- **WHEN** an outcome lists a group as unresolved
- **THEN** the report includes its finding, votes, reason/evidence when present, and the statement that expanded-context verification remained uncertain

### Requirement: Coverage proves lane participation

Every report MUST include a per-lane table of planned dispatched runs, valid runs, findings, and uncovered controller hunk count plus the canonical IDs of any uncovered hunks. It MUST include kept/excluded diff character accounting and chunk count only when an inline budget report exists.

#### Scenario: One two-chunk inline lane fails entirely

- **WHEN** an activated inline lane has three replicas over two chunks and zero valid outputs
- **THEN** the coverage table contains that lane with `6 / 0 / 0` and the budget summary identifies two chunks rather than making the lane indistinguishable from an omitted lane

#### Scenario: Agentic lane leaves one hunk uncovered

- **WHEN** bounded coverage verification ends with one canonical hunk ID uncovered for a lane
- **THEN** the coverage table gives that lane an uncovered count of one and the report renders the canonical hunk ID without a diff-budget summary

### Requirement: Display folds preserve member detail

Pattern folds MUST render the repeated rule and every member location, region folds MUST contribute adjacency labels, and differing member adjudication reasons MUST render as per-member reason and evidence blocks.

#### Scenario: Pattern members have different reasons

- **WHEN** a four-location pattern fold has non-identical adjudication reasons
- **THEN** the report lists each file and line with its own reason and evidence instead of showing one representative explanation

### Requirement: Publication is COMMENT-only

Every GitHub review payload MUST hardcode `event: COMMENT`, and no reporting or publication API SHALL construct an APPROVE or REQUEST_CHANGES event.

#### Scenario: Publish payload is built

- **WHEN** the report contains blocker findings
- **THEN** the GitHub review event remains COMMENT

### Requirement: Publication is dry-run by default

The `rvw publish` command MUST write `publish-payload.json` without a network call unless `--execute` is supplied.

#### Scenario: Operator inspects payload

- **WHEN** an operator runs `rvw publish --run <id>` without `--execute`
- **THEN** the payload is saved under the run directory and no GitHub review is created

### Requirement: Confirmed anchors become inline comments

Confirmed groups that have a new-side line and `anchorable: true` MUST be emitted as right-side inline comments, while non-anchorable or non-confirmed content MUST remain in the review body.

#### Scenario: Finding is outside the diff

- **WHEN** a confirmed finding has `anchorable: false`
- **THEN** it remains in the body and is not sent as an inline comment

### Requirement: HTTP 422 fallback is bulk and bounded

Publication MUST retry exactly once after a 422 response to a payload containing inline comments by moving every inline item into an `앵커 실패 항목` body section, and MUST perform at most two GitHub API calls.

#### Scenario: One inline anchor is rejected

- **WHEN** GitHub rejects the initial bulk review with HTTP 422
- **THEN** the second and final call contains no inline comments and places all attempted inline findings in the fallback body section

#### Scenario: Non-422 error occurs

- **WHEN** GitHub returns an error other than 422
- **THEN** publication raises the error without retrying

### Requirement: Gate verdict publication is artifact-derived

The gate MUST generate its publishable verdict from persisted target, discovery, merge, adjudication, coverage, and disposition data, and the verdict MUST contain the run ID, base and head anchors, aggregate verdict counts, per-lane dispatched and valid counts, and each actionable finding's public ID, severity, adjudication verdict, disposition, and reason.

#### Scenario: Later audit reconstructs a gate decision

- **WHEN** a gate verdict contains accepted and must-fix findings across multiple lanes
- **THEN** the saved JSON and Markdown identify every decision and the exact anchored run without relying on aggregate counts alone

### Requirement: Gate publication preserves COMMENT safety

Gate publication MUST be dry-run by default, MUST use the existing COMMENT-only payload construction, MUST NOT expose an APPROVE or REQUEST_CHANGES mode, and MUST retry at most once without inline comments after an HTTP 422 response.

#### Scenario: Gate publication is inspected

- **WHEN** an operator runs gate without `--execute`
- **THEN** rvw writes the COMMENT payload and makes no GitHub publication call

#### Scenario: Gate inline comment is rejected

- **WHEN** GitHub returns HTTP 422 for the first gate payload containing inline comments
- **THEN** rvw performs one final body-only COMMENT attempt and no third request

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

A stack report MUST render captured member metadata and ordinary run references,
MUST summarize each member's local finding verdicts, and MUST render every
lineage's origin claim, ordered descendant observations, evidence, and current
`STILL_PRESENT`, `FIXED_IN`, `REGRESSED_IN`, or `UNCERTAIN` state.

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
  manifest tip head, and the stack report body, contains no inline comments, and
  no GitHub review is created
