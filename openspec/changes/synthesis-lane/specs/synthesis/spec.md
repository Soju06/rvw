## Purpose

Produce reader-oriented review explanations from persisted review evidence without changing review judgments or discovering additional findings.

## ADDED Requirements

### Requirement: Synthesis rewrites persisted evidence after adjudication

Ordinary reviews MUST attempt one synthesis invocation after successful adjudication and before reporting/publication. Inputs MUST come exclusively from persisted PR title/body, base/head refs, non-rejected merged findings with severity, rule, source location and original prose, adjudication reasons/evidence, coverage and failure facts, and presentation including voice. Synthesis MUST NOT discover new evidence, change severity, omit or add finding keys, or alter review judgments. UNCERTAIN findings MUST retain their uncertainty.

#### Scenario: Mixed adjudication results

- **WHEN** persisted results contain confirmed, uncertain and rejected groups
- **THEN** synthesis receives every non-rejected group exactly once and no rejected group, and the original severity and verdict remain authoritative

### Requirement: Synthesis is strict and faithful

The synthesis artifact MUST be strict JSON with exactly `overview`, nullable `first_action`, and `findings`; each finding MUST contain exactly `key`, `title`, `what`, `consequence`, and `fix`. Prose strings MUST be nonblank. Every input finding key MUST occur exactly once. Source paths, identifiers, code and error strings used in explanations MUST remain verbatim. Missing, duplicate or extra keys and internal reviewer vocabulary in prose MUST fail validation.

#### Scenario: Invalid explanation is retried

- **WHEN** the first output fails JSON, schema or fidelity validation
- **THEN** synthesis retries once with validation errors appended and accepts only a valid replacement

### Requirement: Synthesis uses an explanatory repository voice

The prompt MUST lead with PR purpose in the author's terms followed by the overall assessment and first action. It MUST require one idea per short sentence, concrete consequences, sentence-form human titles, one remediation direction, evidence-bounded claims, verbatim source literals, and explanations for terms absent from the codebase. It MUST prohibit condescension, audience meta, exclamation marks, emoji, “simply”, “just”, “obviously”, counts, orchestrator instructions, and internal reviewer vocabulary including “Confirmed:”, “replica”, “adjudicat”, “lane”, “orchestrator”, “verdict”, “discovery”, “5살”, “five-year”, and “다섯 살”. Korean MUST use polite written language (합니다체 with formal register, noncasual neutral without 해요체 otherwise); English MUST be technical and neutral with the configured register. Mixed audience MUST receive additional explanations of terms. Repository guidance MUST be appended as presentation guidance without overriding evidence and fidelity constraints.

#### Scenario: Korean review includes English source literals

- **WHEN** locale is ko and evidence names a path, symbol and English error string
- **THEN** explanations use Korean and retain each source literal byte-for-byte

### Requirement: Synthesis failures are bounded and nonfatal

Synthesis MUST use the resolved Codex model/effort, tool-less execution, review-phase egress restrictions and existing no-output watchdog. Each attempt MUST state a budget of at most 120 seconds capped by the requested runtime deadline and zero tool calls. A second invalid output or runtime failure MUST continue without synthesis, retain diagnostics, and record `fallback:<reason>` without changing the review status. A validated output MUST record `ok`. Cancellation MUST remain cancellation.

#### Scenario: Second malformed output

- **WHEN** both synthesis attempts fail validation
- **THEN** publication uses the fallback view, telemetry records fallback, and the review proceeds with unchanged judgments
