## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Controller-computed scope MUST classify findings as changed, unchanged_in_file, or outside_diff from parsed hunks and diff files; collapse groups MUST use strongest scope and carry effective_severity and demotion_reason while preserving raw severity.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Runtime and enriched findings are separate models

The system MUST accept runtime findings containing `rule_id`, `file`, new-side `line`, `severity`, and `body`, then MUST enrich valid findings with schema version, hunk identity, anchorability, lane ID, and replica number before merge.

#### Scenario: Runtime finding is inside a diff hunk

- **WHEN** a valid runtime finding names an added line in a parsed hunk
- **THEN** discovery emits an enriched finding with that hunk's deterministic ID, `anchorable: true`, and the producing lane and replica

#### Scenario: Runtime finding is outside the diff

- **WHEN** a valid runtime finding names a line outside every parsed hunk
- **THEN** discovery retains it with hunk identity `<file>:*` and `anchorable: false`

### Requirement: Collapse preserves distinct evidence

A collapse group SHALL retain unique finding bodies in encounter order, SHALL retain all member findings, SHALL choose the highest member severity, and SHALL count agreement by distinct replica number.

#### Scenario: Duplicate and distinct bodies

- **WHEN** three members contain bodies `A`, `A`, and `B` with two replica numbers
- **THEN** the group bodies are `A` then `B` and its agreement is 2

### Requirement: Priority exposes independent confidence axes

Every collapse group MUST expose priority axes in descending significance as cross-layer status, replica agreement, pattern repetition, and severity, followed by deterministic location and identity tie-breakers for ordering.

#### Scenario: Repetition strengthens low agreement

- **WHEN** four one-replica groups form one repeated pattern
- **THEN** each retains agreement 1 and receives repetition 4 as a separate priority axis
