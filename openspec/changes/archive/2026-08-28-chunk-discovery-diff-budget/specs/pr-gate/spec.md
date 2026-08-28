## MODIFIED Requirements

### Requirement: Coverage exactly matches the activated plan

Gate MUST require a nonempty activated lane plan with a positive chunk count, MUST derive every planned `(lane, replica, chunk)` combination, MUST require exact equality with the distinct persisted coverage run entries, and MUST require every planned entry to be VALID. It MUST reject missing, duplicate, unexpected, invalid, or aggregate-inconsistent coverage.

#### Scenario: Vacuous run has no dispatches

- **WHEN** discovery contains no coverage rows or a lane reports zero dispatched runs
- **THEN** gate fails coverage and cannot publish

#### Scenario: One planned lane is absent

- **WHEN** the activated plan contains a lane absent from discovery coverage
- **THEN** gate fails even if aggregate valid and dispatched counts are equal

#### Scenario: One chunk combination is missing

- **WHEN** a planned lane-replica-chunk entry is absent while another entry is duplicated or aggregate counts otherwise appear complete
- **THEN** gate fails exact coverage comparison

#### Scenario: One chunk result is invalid

- **WHEN** every planned combination is present but one chunk entry is INVALID
- **THEN** gate fails with that lane, replica, chunk, and machine-readable invalid reason in persisted coverage
