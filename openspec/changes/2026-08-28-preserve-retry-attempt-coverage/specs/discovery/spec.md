## MODIFIED Requirements

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment. A lane-chunk group
MUST receive exactly one replacement wave only when every initial replica is
INVALID and every invalid reason is `unparseable` or
`schema-invalid`; an initial wave MUST NOT contain retry feedback. A timeout,
cancellation, budget, spawn, completion-marker, missing-artifact, or other
invalid reason MUST NOT cause an identical full-wave retry. Any lane-chunk group
with no valid result after its permitted retry decision MUST retain its final
INVALID executions for run-level failure evaluation rather than contributing a
zero-finding PASS. Replacement artifacts and ordered attempt coverage retain the
existing contract, and legacy discovery artifacts continue to load with empty
attempt history.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID with an
  `unparseable` or `schema-invalid` reason
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and performs no further retry

#### Scenario: Replacement prompt names correctable prior failures

- **WHEN** every initial replica of one lane-chunk is INVALID with an
  `unparseable` or `schema-invalid` reason
- **THEN** that lane-chunk's replacement prompt lists each prior replica's invalid reason while another lane's unretried prompt contains none

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

#### Scenario: Retried coverage keeps the initial failure reason

- **WHEN** a lane-chunk retried after an initial `schema-invalid` failure succeeds in the replacement wave
- **THEN** its persisted coverage row is valid, and its attempt records list the initial INVALID attempt with reason `schema-invalid` followed by the valid retry attempt

#### Scenario: Legacy discovery artifact loads

- **WHEN** a `discover.json` persisted before attempt records is loaded
- **THEN** loading succeeds and each coverage run reports empty attempt history
