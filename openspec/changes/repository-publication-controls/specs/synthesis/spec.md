## MODIFIED Requirements

### Requirement: Synthesis rewrites persisted evidence after adjudication

Ordinary reviews MUST, by default, attempt one synthesis invocation after successful adjudication and before reporting/publication. Inputs MUST come exclusively from persisted PR title/body, base/head refs, non-rejected merged findings with severity, rule, source location and original prose, adjudication reasons/evidence, coverage and failure facts, and presentation including voice. Synthesis MUST NOT discover new evidence, change severity, omit or add finding keys, or alter review judgments. UNCERTAIN findings MUST retain their uncertainty.

Repository `synthesis.enabled: false` MUST skip synthesis execution, record `summary.synthesis.status: disabled`, and render the fallback publication view. The default MUST be true.

#### Scenario: Mixed adjudication results

- **WHEN** persisted results contain confirmed, uncertain and rejected groups
- **THEN** synthesis receives every non-rejected group exactly once and no rejected group, and the original severity and verdict remain authoritative

#### Scenario: Repository disables synthesis

- **WHEN** the captured presentation sets synthesis.enabled false
- **THEN** no synthesis runtime is invoked, status is disabled and publication renders the fallback view

### Requirement: Synthesis uses an explanatory repository voice

The prompt MUST lead with PR purpose in the author's terms followed by the overall assessment and first action. It MUST require one idea per short sentence, concrete consequences, sentence-form human titles, one remediation direction, evidence-bounded claims, verbatim source literals, and explanations for terms absent from the codebase. It MUST prohibit condescension, audience meta, exclamation marks, emoji, “simply”, “just”, “obviously”, counts, orchestrator instructions, and unambiguous internal reviewer vocabulary including “Confirmed:”, “replica(s)”, “adjudicat*”, “orchestrator”, “5살”, “five-year”, and “다섯 살”. The prompt MUST place an imperative Language section immediately after Role, before runtime and reader details. It MUST require every Korean prose field to use 합니다체 or every English prose field to use technical-neutral English in the configured register, with a matching-language example. It MUST require every output identifier, path, code fragment and error string to remain in its original form wrapped in backticks. Mixed audience MUST receive additional explanations of terms. Repository guidance MUST be appended as presentation guidance without overriding evidence and fidelity constraints.

The matching-language example MUST be generic and contain no consumer product. Up to three repository `voice.examples`, each at most 200 Unicode characters, MUST follow the generic example. Process phrasing for lane, verdict, discovery and controller MUST be rejected only outside protected literals and only when the term does not occur in any review source text, including finding bodies, evidence, PR title/body and paths. The process patterns MUST cover “the lane”, “this lane”, “lane <id>”, “verdict”, “discovery lane” and “the controller”. Repository `voice.allowed_terms` MUST exempt matching terms from vocabulary rejection without relaxing evidence fidelity or language validation.

#### Scenario: Korean review includes English source literals

- **WHEN** locale is ko and evidence names a path, symbol and English error string
- **THEN** explanations use Korean and retain each used source literal byte-for-byte in backticks

#### Scenario: Domain discovery prose

- **WHEN** a finding path contains discovery and Korean prose uses discovery outside backticks
- **THEN** vocabulary validation accepts that domain term while retaining literal fidelity checks

#### Scenario: Process lane prose

- **WHEN** no source text contains lane and generated prose says “the lane found”
- **THEN** vocabulary validation rejects that process phrase unless lane is explicitly allowed

#### Scenario: Repository provides voice examples

- **WHEN** presentation contains three examples of at most 200 characters each
- **THEN** the prompt places them after its generic example and contains no built-in consumer product example

### Requirement: Synthesis failures are bounded and nonfatal

Synthesis MUST use the resolved Codex model/effort, tool-less execution, review-phase egress restrictions and existing no-output watchdog. Each attempt MUST state a budget of at most 300 seconds capped by the requested runtime deadline and zero tool calls. A second invalid output or runtime failure MUST continue without synthesis, retain diagnostics, and record `fallback:<reason>` without changing the review status. A validated output MUST record `ok`. Disabled execution MUST record `disabled` without invoking the runtime. Cancellation MUST remain cancellation.

#### Scenario: Second malformed output

- **WHEN** both synthesis attempts fail validation
- **THEN** publication uses the fallback view, telemetry records fallback, and the review proceeds with unchanged judgments
