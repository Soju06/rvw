## ADDED Requirements

### Requirement: Diff budget plans ordered file chunks

After generated-path and oversized-file exclusions, discovery MUST partition complete kept file segments with order-preserving greedy next-fit packing, MUST place every kept file in exactly one chunk, and MUST keep each chunk's retained segment characters at or below 400,000. The planner MUST return one chunk when the retained diff fits, MUST preserve that filtered diff byte-for-byte, and MUST record ordered chunk count, file placement, and character accounting.

#### Scenario: Ordinary diff fits one chunk

- **WHEN** retained file segments total at most 400,000 characters
- **THEN** the planner returns one chunk whose diff bytes equal the previously filtered result

#### Scenario: Large source diff requires multiple chunks

- **WHEN** retained file segments total about 735,000 characters and every file is at most 200,000 characters
- **THEN** the planner returns at least two chunks in source order, every chunk is at most 400,000 retained characters, and every kept file appears exactly once

### Requirement: Chunk prompts expose the whole file plan

Every discovery prompt MUST identify its `chunk k/N`, MUST list every kept file path in source order, MUST mark which listed files are present in the current chunk, and MUST include only that chunk's complete diff segments in its unified-diff section.

#### Scenario: Lane reviews the first of two chunks

- **WHEN** the first chunk contains `src/a.py` and the second contains `src/b.py`
- **THEN** the first prompt says `chunk 1/2`, lists both paths, marks `src/a.py` as included, and embeds no `src/b.py` diff segment

## MODIFIED Requirements

### Requirement: Discovery dispatches three replicas by default

The DISCOVER stage MUST plan three runs per active lane per diff chunk by default and MUST dispatch all lane-replica-chunk runs through one shared wave.

#### Scenario: Four lanes activate over two chunks

- **WHEN** discovery uses the default replica count
- **THEN** it submits 24 planned runs without waiting for one lane or chunk to finish before submitting another

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment, and the dispatcher MUST retry a lane-chunk group exactly once only when every initial replica for that lane and chunk is INVALID.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and performs no further retry

### Requirement: Discovery records per-lane coverage

Discovery MUST record each activated lane's aggregate dispatched, valid, and finding counts and MUST record exactly one strict run entry for every planned `(replica, chunk)` combination, including entries with zero findings or INVALID results and their machine-readable invalid reasons.

#### Scenario: One chunk remains invalid

- **WHEN** a two-chunk, three-replica lane has five VALID final results and one INVALID final result
- **THEN** coverage reports six dispatched, five valid, and six distinct run entries identifying the invalid replica-chunk combination

## REMOVED Requirements

### Requirement: Aggregate diff overage fails loudly

**Reason**: The aggregate limit is now a per-prompt chunk budget; deterministic rejection caused legitimate large-source reviews to fail without a recovery path.

**Migration**: Consumers use the returned chunk list and report placement instead of catching `DiffBudgetExceeded`; the exception is removed without an alias.
