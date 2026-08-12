## MODIFIED Requirements

### Requirement: Verdicts use strict-majority voting

The stage MUST run three adjudication replicas by default and MUST select `CONFIRMED`, `REJECTED`, or `UNCERTAIN` only when that verdict has more than half of the valid replica votes, otherwise it MUST select `UNCERTAIN`. It MUST preserve any explicitly requested positive replica count, including one-replica single-vote mode.

#### Scenario: One valid default vote confirms

- **WHEN** only one default adjudication replica returns a valid CONFIRMED vote and the other two replicas are invalid
- **THEN** CONFIRMED wins because its one vote is more than half of the one valid vote

#### Scenario: Three-way disagreement in explicit replication mode

- **WHEN** three valid replicas vote CONFIRMED, REJECTED, and UNCERTAIN
- **THEN** the merged verdict is UNCERTAIN

#### Scenario: Two explicitly requested replicas confirm

- **WHEN** two of three explicitly requested valid votes are CONFIRMED
- **THEN** the merged verdict is CONFIRMED

#### Scenario: Explicit single-vote mode confirms

- **WHEN** adjudication is explicitly requested with one replica and its valid vote is CONFIRMED
- **THEN** CONFIRMED wins because its one vote is more than half of the one valid vote
