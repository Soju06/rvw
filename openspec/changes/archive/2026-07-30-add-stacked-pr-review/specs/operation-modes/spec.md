## ADDED Requirements

### Requirement: Stack review composes the common pipeline

The `stack review` command MUST invoke the same target resolution, DISCOVER,
MERGE, ADJUDICATE, and REPORT implementation used by ordinary review for each
member, and stack orchestration MUST be limited to member sequencing, immutable
anchor checks, lineage rechecks, and stack-level artifacts.

#### Scenario: One stack member is reviewed

- **WHEN** stack orchestration reaches a captured member checkout
- **THEN** it calls the common pipeline rather than a stack-specific discovery
  or merge implementation

#### Scenario: Ordinary review runs after stack support is installed

- **WHEN** `rvw review` or `rvw auto` is invoked
- **THEN** its existing stage order, defaults, pause behavior, and artifact
  contract remain unchanged
