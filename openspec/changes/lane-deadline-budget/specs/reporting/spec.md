## MODIFIED Requirements

### Requirement: GitHub publication has a separate human view

GitHub review and inline bodies MUST be rendered from persisted finding evidence as a publication view separate from diagnostic `report.md`. The body MUST contain localized outcome, blocker, and warning/suggestion sections, and an uncertainty section only when nonempty. REJECTED findings MUST NOT be published. A finding MUST retain its path:line location, localized severity, short code-formatted lane rule ID, human title, impact and correction, and verbatim evidence fence. Partial coverage MUST add a localized sentence stating the number of unreviewed change regions. When any lane has a final INVALID planned execution, the outcome MUST add a localized sentence stating the number of unfinished rule sets followed by their lane identifiers verbatim, joined by `, `, in coverage order. The publication view MUST omit job/run IDs, head/base SHAs, generation timestamps, public finding IDs/group keys, replica agreement and votes, fold diagnostics, coverage tables, diff budgets, coerced-rejection counts, generator/build footers, and synthesis instructions. A configured footer MUST be included. Inline comments MUST render severity and rule tag, title, impact/correction, then evidence. Existing anchor eligibility and bounded 422 fallback MUST be preserved, with fallback bodies using the same human view.

#### Scenario: Mixed fixture publishes in Korean

- **WHEN** one blocker, two warnings, one rejected finding, one uncertain finding, and one uncovered hunk are rendered with locale ko
- **THEN** the view includes 수정 필요, 확인 필요, the uncertainty section, rule tags, locations and 검토되지 않은 변경 구간이 1곳 있습니다. while excluding rejected findings and diagnostic metadata

#### Scenario: Same fixture publishes in English

- **WHEN** the same evidence is rendered with locale en
- **THEN** the same selected findings and structure use English chrome

#### Scenario: Two lanes did not finish

- **WHEN** `correctness` and `hygiene` end with INVALID final executions and the other lanes are valid
- **THEN** the Korean summary ends with `검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene.` and the English summary with `Rule sets that did not finish: 2 (correctness, hygiene).`, and a review with no failed lane has no such sentence

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
