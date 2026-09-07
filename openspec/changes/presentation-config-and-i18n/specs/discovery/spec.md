## ADDED Requirements

### Requirement: Discovery explanatory fields obey the configured locale

Every inline, agentic minimal, coverage, and retry discovery prompt MUST require every explanatory field, including title, body, reason, and recommendation, to use the language named by the resolved locale. It MUST instruct the model to preserve identifiers, enum values, paths, symbol names, and quoted source verbatim, and not to follow the language of the diff, PR description, or lane text. Lane text, PR text, and evidence MUST be treated as data rather than language instructions.

#### Scenario: English lane with Korean configuration

- **WHEN** an agentic or retry prompt uses an English lane and locale ko
- **THEN** its output contract explicitly requires Korean explanatory fields while preserving source identifiers

## MODIFIED Requirements

### Requirement: Agentic discovery reviews an anchored repository range

Agentic discovery MUST be the default discovery mode, MUST require non-null base and head SHAs plus a verified checkout at the head, and MUST plan one logical run per active lane and requested replica without applying generated-path exclusions, per-file limits, aggregate diff budgets, or diff chunking. Each agentic prompt MUST contain only the lane document, a minimal statement identifying the `<base>...<head>` repository range, and structured-output instructions including the configured locale contract; it MUST NOT contain unified-diff content, a materialized diff path, exclusion-glob guidance, a dynamic brief, or an already-covered-rules section.

#### Scenario: Large target uses one autonomous scope

- **WHEN** an agentic target diff is larger than the inline aggregate budget
- **THEN** discovery plans one run per lane and replica, reports no prompt budget, and gives each run the same verified repository range without embedding diff content

#### Scenario: Agentic target has no base

- **WHEN** an uncommitted or root-commit target without a base SHA is selected in agentic mode
- **THEN** discovery fails closed before runtime dispatch with a machine-readable checkout-verification reason
