## MODIFIED Requirements

### Requirement: Adjudication runs against actual source

Every adjudication replica MUST execute read-only in the provisioned target checkout and SHALL receive the reviewed diff plus every preserved body for each candidate. The reviewed diff MUST be the budget-filtered diff produced by the shared reviewed-diff projection, so content excluded as a generated path or an oversized file MUST NOT appear in an adjudication prompt, and its visible exclusion header MUST be retained. The adjudication prompt MUST NOT be partitioned into chunks.

#### Scenario: Candidate depends on surrounding code

- **WHEN** an adjudicator checks a collapse group
- **THEN** it can inspect the target checkout while seeing all replica descriptions and the reviewed unified diff in its prompt

#### Scenario: Target diff contains a lockfile and an oversized file

- **WHEN** discovery excludes a lockfile as a generated path and one file as oversized
- **THEN** neither excluded segment appears in the adjudication prompt, and the prompt names both paths in the exclusion header

#### Scenario: Retained diff fits one discovery chunk

- **WHEN** discovery plans exactly one chunk for the retained diff
- **THEN** the adjudication prompt's diff content equals that chunk's retained segments byte-for-byte

### Requirement: All-invalid adjudication retries once

An adjudication pass MUST retry its entire replica wave exactly once when every replica is INVALID and MUST otherwise use the valid results without retrying individual invalid replicas. The one retry prompt MUST carry each prior replica's machine-readable invalid reason, and an initial wave prompt MUST NOT contain that retry feedback.

#### Scenario: One replica is valid

- **WHEN** one adjudication replica is VALID and two are INVALID
- **THEN** no replacement wave runs and voting uses the one valid output

#### Scenario: Every replica is invalid

- **WHEN** all three adjudication replicas return INVALID with machine-readable reasons
- **THEN** the one retry prompt identifies each prior replica's invalid reason while the initial prompt contained none
