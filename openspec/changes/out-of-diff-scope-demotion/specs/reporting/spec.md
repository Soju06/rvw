## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Demoted findings MUST render in a localized 참고 section with disclosure and provenance, contribute no actionable counts, and MUST be body-only without inline threads.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Reports separate verdict classes

An adjudicated diagnostic report MUST render CONFIRMED groups in the confirmed section, unresolved UNCERTAIN groups in the localized uncertainty section, and REJECTED groups in collapsible details without silently dropping any class.

#### Scenario: Expanded pass remains uncertain

- **WHEN** an outcome lists a group as unresolved
- **THEN** the report includes its finding, votes, reason/evidence when present, and the statement that expanded-context verification remained uncertain

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
