## ADDED Requirements

### Requirement: Gate publication uses localized human findings

Gate publication MUST derive its body from the persisted verdict and presentation snapshot through the human publication view and locale catalogs. It MUST retain PASS/BLOCK, the actionable finding list, and human disposition reasons, and MUST omit run IDs, actor identity, and inheritance internals from publication prose. Structured gate verdict artifacts MUST retain those diagnostic facts. Publication MUST satisfy the shared language gate without changing disposition, anchor, or COMMENT safety semantics.

#### Scenario: Accepted blocker is published

- **WHEN** a completed gate contains an owner-authorized accepted blocker and inheritance provenance
- **THEN** the human view shows its finding and reason while JSON retains actor and inheritance facts

## MODIFIED Requirements

### Requirement: Fully inherited runs proceed without pausing

When every actionable finding of the current run is covered by a hunk-and-body-digest-verified exact-ID carried acceptance, gate MUST persist the generated disposition document under the run directory and MUST continue into disposition validation and verdict construction in the same invocation instead of exiting for a resume round. Sticky accepted entries MUST count as requiring operator completion even though their generated decisions are `accepted`. A partial-inheritance pause MUST report and persist the source run ID plus exact-carried, sticky, reason-only prefilled, and blank counts grouped by machine-readable reason. Owner authorization for accepted blockers MUST be re-verified in the inheriting run, and a failed re-verification MUST persist the finding ID, verified actor, and returned permission. An operational authorization failure MUST persist a BLOCK verdict containing affected blocker IDs, the resolved actor when available, the failed lookup step, and a secret-redacted subprocess diagnostic of at most 500 characters with C0/C1 and Unicode format controls removed by deletion and explicit truncation. Newline placeholders MAY become spaces only after credential redaction. A successful actor or permission subprocess whose trimmed output is empty MUST be classified as the corresponding lookup's operational failure, not as an authorization denial. The diagnostic MUST mask GitHub token prefixes, authorization-header and bearer values, and long base64 or hexadecimal runs before any console or artifact consumer receives it. The structured verdict JSON artifact MUST retain each carried or sticky record's inherited run identifier and inheritance tier; publication prose MUST omit this inheritance metadata.

#### Scenario: Authorization subprocess emits sensitive stderr

- **WHEN** actor or permission lookup fails with stderr containing credentials, control characters, or an oversized response
- **THEN** gate preserves the failed step and exit status while every console, JSON, and Markdown diagnostic contains only the bounded redacted form

#### Scenario: Every actionable finding was previously accepted

- **WHEN** all actionable findings receive tier-one carried acceptances from the inherited verdict
- **THEN** gate validates the persisted generated document and reports a verdict in the same invocation

#### Scenario: One finding is new

- **WHEN** one actionable finding has no match in the inherited verdict
- **THEN** gate writes the partially prefilled template and exits nonzero for human completion

#### Scenario: One finding is sticky

- **WHEN** all other actionable findings exact-carry but one receives `unique_pair_sticky`
- **THEN** gate writes the generated template with sticky provenance and exits for human completion

#### Scenario: Sticky summary is distinct

- **WHEN** inheritance produces exact-carried, sticky, reason-only prefilled, and blank outcomes
- **THEN** the pause summary reports separate counts for all four categories and does not include sticky entries in carried

#### Scenario: Carried blocker acceptance without admin actor

- **WHEN** every actionable finding carries but one accepted blocker's re-verified actor lacks repository admin permission
- **THEN** gate fails closed and does not publish
