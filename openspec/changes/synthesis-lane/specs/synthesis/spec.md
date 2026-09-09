## Purpose

Produce reader-oriented review explanations from persisted review evidence without changing review judgments or discovering additional findings.

## ADDED Requirements

### Requirement: Synthesis rewrites persisted evidence after adjudication

Ordinary reviews MUST attempt one synthesis invocation after successful adjudication and before reporting/publication. Inputs MUST come exclusively from persisted PR title/body, base/head refs, non-rejected merged findings with severity, rule, source location and original prose, adjudication reasons/evidence, coverage and failure facts, and presentation including voice. Synthesis MUST NOT discover new evidence, change severity, omit or add finding keys, or alter review judgments. UNCERTAIN findings MUST retain their uncertainty.

#### Scenario: Mixed adjudication results

- **WHEN** persisted results contain confirmed, uncertain and rejected groups
- **THEN** synthesis receives every non-rejected group exactly once and no rejected group, and the original severity and verdict remain authoritative

### Requirement: Synthesis is strict and faithful

The synthesis artifact MUST be strict JSON with exactly `overview`, nullable `first_action`, and `findings`; each finding MUST contain exactly `key`, `title`, `what`, `consequence`, and `fix`. Prose strings MUST be nonblank. Every input finding key MUST occur exactly once. Fidelity MUST mean no mutation, not full repetition: every backtick/quoted literal, path, code fragment and code identifier used in any prose field MUST appear byte-for-byte in its source (original finding bodies, adjudication reason/evidence and path). Finding prose MUST use its own finding sources; overview and first_action MAY use sources from any included finding. Invented literals and edited or case-changed variants MUST fail validation. Source literals MAY be omitted, including when the adjudication reason does not establish the original claim. Missing, duplicate or extra keys and internal reviewer vocabulary in prose MUST fail validation.

#### Scenario: Invalid explanation is retried

- **WHEN** the first output fails JSON, schema or fidelity validation
- **THEN** synthesis retries once with validation errors appended and accepts only a valid replacement

#### Scenario: Unsupported source claim is omitted

- **WHEN** adjudication does not establish a claim containing a source literal and synthesis omits that claim and literal
- **THEN** omission passes fidelity validation while an invented or mutated output literal fails

### Requirement: Synthesis uses an explanatory repository voice

The prompt MUST lead with PR purpose in the author's terms followed by the overall assessment and first action. It MUST require one idea per short sentence, concrete consequences, sentence-form human titles, one remediation direction, evidence-bounded claims, verbatim source literals, and explanations for terms absent from the codebase. It MUST prohibit condescension, audience meta, exclamation marks, emoji, “simply”, “just”, “obviously”, counts, orchestrator instructions, and internal reviewer vocabulary including “Confirmed:”, “replica”, “adjudicat”, “lane”, “orchestrator”, “verdict”, “discovery”, “5살”, “five-year”, and “다섯 살”. The prompt MUST place an imperative Language section immediately after Role, before runtime and reader details. It MUST require every Korean prose field to use 합니다체 or every English prose field to use technical-neutral English in the configured register, with a matching-language example. It MUST require every output identifier, path, code fragment and error string to remain in its original form wrapped in backticks. Mixed audience MUST receive additional explanations of terms. Repository guidance MUST be appended as presentation guidance without overriding evidence and fidelity constraints.

#### Scenario: Korean review includes English source literals

- **WHEN** locale is ko and evidence names a path, symbol and English error string
- **THEN** explanations use Korean and retain each used source literal byte-for-byte in backticks

### Requirement: Synthesis validates the configured language per field

Synthesis validation MUST call the existing language checker separately for overview, non-null first_action, and every finding title, what, consequence and fix, using the configured locale and source literals as protected literals. Generated synthesis and retained artifact validation MUST use the persisted presentation locale. Language failures MUST raise ValueError with diagnostics beginning `synthesis prose is not in locale '<locale>':` and identifying every failing field. The single validation retry MUST receive these field-specific diagnostics and the required locale. Existing language thresholds, publication language checking, retry count, runtime bounds and fallback reasons MUST remain unchanged.

#### Scenario: English output under Korean configuration

- **WHEN** locale is ko and one or more prose fields contain English explanations
- **THEN** synthesis rejects the output and retry feedback identifies all failing fields and locale ko

#### Scenario: Korean prose surrounds English code

- **WHEN** locale is ko and Korean explanations include backticked source identifiers or error strings
- **THEN** those literals do not count against the language ratio and the Korean explanations pass

### Requirement: Synthesis failures are bounded and nonfatal

Synthesis MUST use the resolved Codex model/effort, tool-less execution, review-phase egress restrictions and existing no-output watchdog. Each attempt MUST state a budget of at most 120 seconds capped by the requested runtime deadline and zero tool calls. A second invalid output or runtime failure MUST continue without synthesis, retain diagnostics, and record `fallback:<reason>` without changing the review status. A validated output MUST record `ok`. Cancellation MUST remain cancellation.

#### Scenario: Second malformed output

- **WHEN** both synthesis attempts fail validation
- **THEN** publication uses the fallback view, telemetry records fallback, and the review proceeds with unchanged judgments
