## MODIFIED Requirements

### Requirement: Synthesis is strict and faithful

The synthesis artifact MUST be strict JSON with exactly `overview`, nullable `first_action`, and `findings`; each finding MUST contain exactly `key`, `title`, `what`, `consequence`, and `fix`. Prose strings MUST be nonblank. Every input finding key MUST occur exactly once. Fidelity MUST mean no mutation, not full repetition: invention checks MUST apply only to backticked spans and bare path-like tokens. Ordinary unbackticked words, acronyms, identifiers and quoted prose MUST NOT be rejected as invented literals. Finding prose MUST use its own original bodies, adjudication reason/evidence and path plus persisted PR title/body; overview and first_action MUST accept sources from any included finding plus persisted PR title/body, including when no findings remain. Generated and retained artifact validation MUST use the same persisted PR text. Checked literals MUST match source text with identifier/path boundaries and unchanged case and underscores, allowing runs of whitespace to collapse in both the span and an individual source text. A source path composed as `path:line` MUST also pass when the line is the finding's source line for that path or a line explicitly quoted in that finding's evidence. Invented identifiers/paths, shortened tokens, unsupported line numbers and case/underscore mutations MUST fail validation. Source literals MAY be omitted, including when the adjudication reason does not establish the original claim. Missing, duplicate or extra keys and internal reviewer vocabulary in prose MUST fail validation. Each invented-literal diagnostic MUST identify its prose field and literals and state on one line that they were "not found in finding bodies, adjudication reason, evidence, or pull request text".

#### Scenario: Invalid explanation is retried

- **WHEN** the first output fails JSON, schema or fidelity validation
- **THEN** synthesis retries once with validation errors appended and accepts only a valid replacement

#### Scenario: Unsupported source claim is omitted

- **WHEN** adjudication does not establish a claim containing a source literal and synthesis omits that claim and literal
- **THEN** omission passes fidelity validation while an invented or mutated output literal fails

#### Scenario: PR terminology appears in Korean explanations

- **WHEN** Korean overview, first_action or finding prose uses bare API or a backticked feature name from the persisted PR title/body
- **THEN** invention validation accepts that terminology during generation and retained replay

#### Scenario: Evidence is composed without token mutation

- **WHEN** a backticked span composes a source path with an established line number or repeats source code with different whitespace
- **THEN** fidelity accepts the span while rejecting an invented path, unsupported line number or case/underscore mutation
