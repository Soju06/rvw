## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Gate actionability, policy thresholds, and exit status MUST use effective_severity; demoted blockers MUST yield PASS when no actionable blocker remains.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Actionable dispositions use exact public finding IDs

Gate MUST classify CONFIRMED and UNCERTAIN groups as actionable, MUST require exactly one strict disposition record for every actionable public finding ID, and MUST reject duplicate, omitted, unknown, or REJECTED-group IDs. Each disposition MUST contain one of `accepted` or `must_fix` and a nonblank human-authored reason. A disposition record MAY carry an `inherited_from` run identifier, and records without it MUST remain valid. When `inherited_from` is present, gate MUST reject the document with machine-readable reason `inherited_from_unbound` unless the named run is the selected `--inherit` source and a matcher recomputed from that source carried or prefilled the finding.

#### Scenario: Duplicate record masks an omission

- **WHEN** a disposition file repeats one finding ID and omits another actionable finding ID
- **THEN** gate rejects the file rather than accepting equal aggregate counts

#### Scenario: No disposition file is available

- **WHEN** a completed review has actionable findings, no disposition file is supplied, and the findings are not fully covered by inherited acceptances
- **THEN** gate writes a keyed disposition template for that run and exits nonzero without rerunning review

#### Scenario: Hand-authored provenance is not bound to a source

- **WHEN** a disposition record names an inherited run but the invocation has no matching `--inherit` source or the recomputed matcher left that finding unmatched
- **THEN** gate rejects the document with machine-readable reason `inherited_from_unbound`

### Requirement: Gate verdict and exit are fail-closed

Gate MUST write a reconstructable verdict artifact after artifact-backed validation, MUST report `PASS` only when anchors, checkout, coverage, dispositions, and owner checks pass and no disposition is `must_fix`, and MUST otherwise report `BLOCK`. The command MUST exit 0 for PASS, 1 for BLOCK or a failed gate invariant, 2 for invalid invocation or disposition syntax, and 3 for checkout, GitHub, or other operational failure.

#### Scenario: Finding is marked must-fix

- **WHEN** every actionable ID is present but one disposition is `must_fix`
- **THEN** the verdict identifies that finding, reports BLOCK, and exits 1

#### Scenario: Accepted findings satisfy all invariants

- **WHEN** every actionable finding is accepted, every blocker acceptance is owner-authorized, and anchors and coverage pass
- **THEN** gate reports PASS and exits 0
