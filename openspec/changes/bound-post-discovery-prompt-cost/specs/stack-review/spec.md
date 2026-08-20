## MODIFIED Requirements

### Requirement: Presence adjudication is strict and bounded

Presence outputs MUST use deterministic batch-local IDs for supplied lineages,
MUST name only those supplied IDs, MUST contain no duplicate IDs, and MUST use
only `PRESENT`, `ABSENT`, or `UNCERTAIN`. The system MUST map local IDs back to
persisted lineage IDs without requiring the model to relay stable SHA-1 IDs.
Missing output MUST vote UNCERTAIN, PRESENT or ABSENT without nonblank evidence
MUST be coerced to UNCERTAIN, a wave with no valid replicas MUST retry exactly
once with the prior replicas' machine-readable invalid reasons in the prompt,
and candidates still uncertain MUST receive one expanded-context pass at twice
the initial deadline. The descendant diff supplied to a presence prompt MUST be
the budget-filtered reviewed diff, so generated-path and oversized-file content
MUST NOT appear in a presence prompt while its visible exclusion header is
retained.

#### Scenario: Candidate is omitted by a valid replica

- **WHEN** a valid presence response omits one supplied local lineage ID
- **THEN** that replica contributes an UNCERTAIN vote for the persisted lineage

#### Scenario: Replica repeats a local lineage ID

- **WHEN** one presence response contains the same batch-local lineage ID twice
- **THEN** that response is invalid rather than silently retaining one item

#### Scenario: All replicas are invalid

- **WHEN** every presence replica in a wave returns an invalid result
- **THEN** the one retry prompt identifies each prior replica's invalid reason

#### Scenario: Absence has no evidence

- **WHEN** a response votes ABSENT with whitespace-only evidence
- **THEN** the vote is stored as UNCERTAIN

#### Scenario: Descendant diff contains generated content

- **WHEN** a descendant head's diff contains a lockfile alongside source changes
- **THEN** the presence prompt omits the lockfile segment and names it in the
  exclusion header

#### Scenario: Initial result remains uncertain

- **WHEN** no presence value receives a strict majority
- **THEN** only that uncertain lineage receives one expanded-context pass
