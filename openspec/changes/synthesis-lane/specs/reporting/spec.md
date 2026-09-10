## MODIFIED Requirements

### Requirement: Report sections are machine-generated except synthesis

The system MUST retain target metadata, finding sections, verdict details, coverage, budget accounting, and generator version in diagnostic artifacts. Diagnostic report sections MUST remain machine-generated except optional synthesis; their headings and placeholders MUST use locale catalogs. An explicit `rvw report --synthesis` file MUST override lane synthesis for report.md. Otherwise validated lane overview and first action MUST supply that section. When neither exists, the diagnostic placeholder MUST be neutral and non-instructional in both locales. Publication MUST NOT publish synthesis instructions.

#### Scenario: No synthesis is supplied

- **WHEN** REPORT renders without an operator file or validated lane synthesis
- **THEN** the synthesis section says “No synthesis was supplied.” in English or “종합이 제공되지 않았습니다.” in Korean and every other section is machine-rendered

#### Scenario: Operator overrides lane synthesis

- **WHEN** both a validated synthesis artifact and --synthesis file exist
- **THEN** report.md uses the operator file and the publication view uses the validated artifact

### Requirement: Confirmed anchors become inline comments

Confirmed groups that have a new-side line and `anchorable: true` MUST be emitted as right-side inline comments. Every non-rejected finding MUST also remain in its body section, including findings posted inline. With synthesis, posted-inline findings MUST have a short body entry containing title, source location and consequence while inline items retain the full explanation. Without synthesis the body MUST retain the existing full finding shape. An empty-section message MUST appear only when that section contains zero findings.

#### Scenario: Finding is outside the diff

- **WHEN** a confirmed finding has `anchorable: false`
- **THEN** it remains in the body and is not sent as an inline comment

#### Scenario: Required changes have inline threads

- **WHEN** the summary counts two confirmed blockers posted inline
- **THEN** the body lists both blockers under required changes and does not show an empty-section message there

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

## ADDED Requirements

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
