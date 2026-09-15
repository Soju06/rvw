## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Synthesis input MUST contain only actionable groups after controller scope classification. Informational groups MUST remain visible in the controller-rendered 참고 section and MUST not be rewritten by synthesis as actionable findings.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Synthesis rewrites persisted evidence after adjudication

Ordinary reviews MUST, by default, attempt one synthesis invocation after successful adjudication and before reporting/publication. Inputs MUST come exclusively from persisted PR title/body, base/head refs, non-rejected merged findings with severity, rule, source location and original prose, adjudication reasons/evidence, coverage and failure facts, and presentation including voice. Synthesis MUST NOT discover new evidence, change severity, omit or add finding keys, or alter review judgments. UNCERTAIN findings MUST retain their uncertainty.

Informational findings whose `effective_severity` is `info` MUST be excluded from the synthesis candidate set, prompt, and `SynthesisDocument.findings`; overview and `first_action` MUST be written over actionable groups only.

Repository `synthesis.enabled: false` MUST skip synthesis execution, record `summary.synthesis.status: disabled`, and render the fallback publication view. The default MUST be true.

#### Scenario: Mixed adjudication results

- **WHEN** persisted results contain confirmed, uncertain and rejected groups
- **THEN** synthesis receives every non-rejected group exactly once and no rejected group, and the original severity and verdict remain authoritative

#### Scenario: Repository disables synthesis

- **WHEN** the captured presentation sets synthesis.enabled false
- **THEN** no synthesis runtime is invoked, status is disabled and publication renders the fallback view

### Requirement: Synthesis is strict and faithful

The synthesis artifact MUST be strict JSON with exactly `overview`, nullable `first_action`, and `findings`; each finding MUST contain exactly `key`, `title`, `what`, `consequence`, and `fix`. Prose strings MUST be nonblank. Every input finding key MUST occur exactly once. Fidelity MUST mean no mutation, not full repetition: invention checks MUST apply only to backticked spans and bare path-like tokens. Ordinary unbackticked words, acronyms, identifiers and quoted prose MUST NOT be rejected as invented literals. Finding prose MUST use its own original bodies, adjudication reason/evidence and path plus persisted PR title/body; overview and first_action MUST accept sources from any included finding plus persisted PR title/body. Generated and retained artifact validation MUST use the same persisted PR text. Checked literals MUST match source text with identifier/path boundaries and unchanged case and underscores, allowing runs of whitespace to collapse in both the span and an individual source text. A source path composed as `path:line` MUST also pass when the line is the finding's source line for that path or a line explicitly quoted in that finding's evidence. Invented identifiers/paths, shortened tokens, unsupported line numbers and case/underscore mutations MUST fail validation. Source literals MAY be omitted, including when the adjudication reason does not establish the original claim. Missing, duplicate or extra keys and internal reviewer vocabulary in prose MUST fail validation. Each invented-literal diagnostic MUST identify its prose field and literals and state on one line that they were "not found in finding bodies, adjudication reason, evidence, or pull request text".

#### Scenario: Invalid explanation is retried

- **WHEN** the first output fails JSON, schema or fidelity validation
- **THEN** synthesis retries once with validation errors appended and accepts only a valid replacement

#### Scenario: Unsupported source claim is omitted

- **WHEN** adjudication does not establish a claim containing a source literal and synthesis omits that claim and literal
- **THEN** omission passes fidelity validation while an invented or mutated output literal fails

### Requirement: Informational findings stay outside synthesis

Informational findings MUST be excluded from synthesis input, including the candidate set, prompt, and `SynthesisDocument.findings`; synthesis overview and `first_action` MUST cover actionable groups only. `validate_synthesis` MUST reject a synthesized finding ID belonging to an informational group through the existing identity validation path. The publication view MUST render the localized 참고 section deterministically from controller adjudication state after the synthesized actionable body, including each rule ID, location, scope disclosure, raw-severity provenance, and adjudicated finding body. Actionable counts MUST remain controller-derived.

#### Scenario: Informational findings are absent from synthesis

- **WHEN** an adjudicated merge contains an outside-diff blocker and a changed blocker
- **THEN** the synthesis prompt and candidate document contain only the changed blocker, while publication still renders the outside-diff blocker in the 참고 section

#### Scenario: Informational identity is rejected

- **WHEN** a synthesized document contains the key of an informational group
- **THEN** validation rejects it with the existing synthesis finding identity mismatch diagnostic

#### Scenario: Reference rendering is independent of synthesis status

- **WHEN** synthesis succeeds or falls back for a merge containing informational findings
- **THEN** publication renders the same controller-derived 참고 entries after the actionable content
