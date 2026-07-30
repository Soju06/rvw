# adjudication

## Purpose

Define source-grounded, replicated verdicts for merged finding groups and a bounded escalation path for uncertainty.

## Requirements

### Requirement: Adjudication is isolated from discovery

The adjudicator MUST evaluate only supplied collapse groups, MUST use a schema whose `group_key` enum contains only those groups, and MUST be instructed not to introduce new findings.

#### Scenario: Adjudicator notices another defect

- **WHEN** a model observes an unrelated issue while checking a supplied candidate
- **THEN** the output contract provides no group key through which to add that issue

### Requirement: Adjudication runs against actual source

Every adjudication replica MUST execute read-only in the provisioned target checkout and SHALL receive the reviewed diff plus every preserved body for each candidate.

#### Scenario: Candidate depends on surrounding code

- **WHEN** an adjudicator checks a collapse group
- **THEN** it can inspect the target checkout while seeing all replica descriptions and the unified diff in its prompt

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

### Requirement: Missing candidate output is an uncertain vote

Each valid adjudication output that omits a supplied group MUST contribute an UNCERTAIN vote for that group.

#### Scenario: Partial batch response

- **WHEN** one valid replica returns items for every group except `group-a`
- **THEN** that replica contributes UNCERTAIN to `group-a` while its returned items vote normally

### Requirement: Rejection requires evidence

A REJECTED item with empty or whitespace-only evidence MUST be coerced to UNCERTAIN and MUST increment the coerced-rejection count.

#### Scenario: Unsupported rejection

- **WHEN** an adjudication item says REJECTED but provides no evidence
- **THEN** its vote becomes UNCERTAIN and the outcome records one coercion

### Requirement: All-invalid adjudication retries once

An adjudication pass MUST retry its entire replica wave exactly once when every replica is INVALID and MUST otherwise use the valid results without retrying individual invalid replicas.

#### Scenario: One replica is valid

- **WHEN** one adjudication replica is VALID and two are INVALID
- **THEN** no replacement wave runs and voting uses the one valid output

### Requirement: Uncertainty receives one expanded-context pass

Groups that remain UNCERTAIN after the initial vote MUST be adjudicated once more with permission to inspect enclosing definitions, referenced symbols, callers, and tests, using twice the initial deadline.

#### Scenario: Initial context is insufficient

- **WHEN** a cache-key candidate is UNCERTAIN because a referenced function is outside the diff
- **THEN** the expanded pass receives only uncertain groups, may inspect that definition, and uses a 2x deadline

### Requirement: Expanded residue remains visible

Any group still UNCERTAIN after the expanded vote MUST remain in the outcome's unresolved list and MUST NOT be converted to REJECTED or silently removed.

#### Scenario: Claim cannot be verified

- **WHEN** the second pass still has no majority verdict
- **THEN** the group remains unresolved for report rendering under the unverified section
