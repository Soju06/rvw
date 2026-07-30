## ADDED Requirements

### Requirement: Verdicts use strict-majority voting

The stage MUST run one adjudication replica by default and MUST select `CONFIRMED`, `REJECTED`, or `UNCERTAIN` only when that verdict has more than half of the valid replica votes, otherwise it MUST select `UNCERTAIN`. It MUST preserve the requested count when callers explicitly request multiple replicas.

#### Scenario: One valid default vote confirms

- **WHEN** the default adjudication replica returns a valid CONFIRMED vote
- **THEN** CONFIRMED wins because its one vote is more than half of the one valid vote

#### Scenario: Three-way disagreement in explicit replication mode

- **WHEN** three explicitly requested valid replicas vote CONFIRMED, REJECTED, and UNCERTAIN
- **THEN** the merged verdict is UNCERTAIN

#### Scenario: Two explicitly requested replicas confirm

- **WHEN** two of three explicitly requested valid votes are CONFIRMED
- **THEN** the merged verdict is CONFIRMED

## REMOVED Requirements

### Requirement: Verdicts use majority voting

**Reason**: The strict-majority algorithm remains unchanged, but its declared default changes from three replicas to one.

**Migration**: Call adjudication with an explicit replica count greater than one when replicated verification is required.
