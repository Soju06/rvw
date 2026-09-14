## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Stack lineage and tip reports MUST retain scope and effective_severity, preserving demotion through body-only tip publication.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Lineage summaries preserve transitions

Confirmed origin findings MUST begin PRESENT, unresolved origin findings MUST
begin UNCERTAIN, and summaries MUST be derived from unique observations ordered
by manifest position rather than numeric PR value. A completed lineage's
observation PRs MUST equal the manifest suffix from its origin through the tip.
A final UNCERTAIN observation MUST yield `UNCERTAIN`; otherwise the latest
conclusive PRESENT-to-ABSENT transition MUST yield `FIXED_IN`, the latest
ABSENT-to-PRESENT transition ending in PRESENT MUST yield `REGRESSED_IN`, and a
lineage ending PRESENT without an earlier absence MUST yield `STILL_PRESENT`.

#### Scenario: Child PR number is lower than its parent

- **WHEN** a valid caller-ordered direct chain is supplied as `--prs 20,15`
- **THEN** observations for PR 20 then PR 15 are accepted in that manifest order

#### Scenario: Finding regresses at the tip

- **WHEN** a lineage history is PRESENT, ABSENT, then PRESENT
- **THEN** the summary is `REGRESSED_IN` at the final member

#### Scenario: Tip presence remains unresolved

- **WHEN** a lineage history is PRESENT, ABSENT, then UNCERTAIN
- **THEN** the summary is `UNCERTAIN` rather than fixed or regressed

### Requirement: Stack publication targets only the tip

Stack publication MUST build one body-only review payload from the persisted
stack report, MUST hardcode `event: COMMENT`, MUST target only the captured tip
pull request, and MUST NOT construct inline comments, approvals, change
requests, or comments on origin members.

#### Scenario: Stack contains findings from PR 1 and PR 2

- **WHEN** a publish payload is built for a stack ending at PR 3
- **THEN** the payload targets PR 3 and contains the stack report only in its
  body
