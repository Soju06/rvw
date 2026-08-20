## MODIFIED Requirements

### Requirement: Diff budget plans ordered file chunks

After generated-path and oversized-file exclusions, discovery MUST partition complete kept file segments with order-preserving greedy next-fit packing, MUST place every kept file in exactly one chunk, and MUST keep each chunk's retained segment characters at or below 400,000. The planner MUST return one chunk when the retained diff fits, MUST preserve that filtered diff byte-for-byte, and MUST record ordered chunk count, file placement, and character accounting. The same module MUST additionally expose an unpartitioned reviewed-diff projection that returns the concatenated kept segments behind the visible exclusion header together with the same exclusion report, so post-discovery stages apply one shared exclusion policy rather than re-implementing it.

#### Scenario: Ordinary diff fits one chunk

- **WHEN** retained file segments total at most 400,000 characters
- **THEN** the planner returns one chunk whose diff bytes equal the previously filtered result

#### Scenario: Large source diff requires multiple chunks

- **WHEN** retained file segments total about 735,000 characters and every file is at most 200,000 characters
- **THEN** the planner returns at least two chunks in source order, every chunk is at most 400,000 retained characters, and every kept file appears exactly once

#### Scenario: A post-discovery stage requests the reviewed diff

- **WHEN** a caller requests the reviewed-diff projection for a target whose diff contains one generated file and one kept file
- **THEN** it receives the kept segment behind the exclusion header plus the exclusion report, and the generated segment is absent

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment, and the dispatcher MUST retry a lane-chunk group exactly once only when every initial replica for that lane and chunk is INVALID. The one replacement prompt for a retried lane-chunk MUST carry each prior replica's machine-readable invalid reason for that lane-chunk, and an initial wave prompt MUST NOT contain that retry feedback. The replacement wave MUST persist its artifacts in a run directory distinct from the initial wave's so the initial INVALID artifacts remain inspectable, while the directory's final component preserves the runtime replica-derivation contract. Persisted run coverage MUST record every attempt's validity and machine-readable invalid reason in execution order, while row-level validity continues to reflect the final attempt, and discovery artifacts persisted before attempt records existed MUST load with empty attempt history.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and performs no further retry

#### Scenario: Replacement prompt names prior failures

- **WHEN** every initial replica of one lane-chunk is INVALID with machine-readable reasons
- **THEN** that lane-chunk's replacement prompt lists each prior replica's invalid reason while another lane's unretried prompt contains none

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

#### Scenario: Retried coverage keeps the initial failure reason

- **WHEN** a lane-chunk retried after an initial `exit_nonzero` failure succeeds in the replacement wave
- **THEN** its persisted coverage row is valid, and its attempt records list the initial INVALID attempt with reason `exit_nonzero` followed by the valid retry attempt

#### Scenario: Legacy discovery artifact loads

- **WHEN** a `discover.json` persisted before attempt records is loaded
- **THEN** loading succeeds and each coverage run reports empty attempt history
