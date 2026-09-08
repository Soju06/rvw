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

An adjudication pass MUST retry its entire replica wave exactly once when every replica is INVALID and MUST otherwise use the valid results without retrying individual invalid replicas. The one retry prompt MUST carry each prior replica's machine-readable invalid reason, and an initial wave prompt MUST NOT contain that retry feedback.

#### Scenario: One replica is valid

- **WHEN** one adjudication replica is VALID and two are INVALID
- **THEN** no replacement wave runs and voting uses the one valid output

#### Scenario: Every replica is invalid

- **WHEN** all three adjudication replicas return INVALID with machine-readable reasons
- **THEN** the one retry prompt identifies each prior replica's invalid reason while the initial prompt contained none

### Requirement: Replica silence is bounded by the runtime watchdog

Each adjudication replica execution MUST inherit the runtime no-output watchdog. A replica terminated for silence MUST be INVALID with reason `no_output_after:<N>s` and MUST cast no vote. The pass MUST NOT retry while at least one replica of the wave is VALID, so the wave wall is bounded by the slowest valid replica wall or by `N` plus the watchdog poll interval and termination grace, rather than by the deadline; when every replica of the wave is terminated for silence, the existing single all-invalid retry applies and its prompt carries those reasons.

#### Scenario: One replica never produces output

- **WHEN** one of three replicas prints only its banner and prompt echo while the other two answer before `N` seconds have elapsed
- **THEN** the silent replica is INVALID with reason `no_output_after:<N>s`, voting uses the two valid outputs, no retry wave runs, and the recorded wave wall is bounded by `N` plus the poll interval and termination grace rather than by the deadline

#### Scenario: Every replica is silent

- **WHEN** all three replicas of a wave are terminated by the watchdog
- **THEN** each is INVALID with a `no_output_after` reason and exactly one retry wave runs with a prompt carrying those reasons

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

### Requirement: No-valid-output adjudication fails as infrastructure

An adjudication pass MUST fail with a run-level adjudication infrastructure error when its initial and one retry wave contain no valid outputs. The error MUST identify the pass and each attempted replica with its normalized failure reason and available exit or log diagnostics, and no outcome with a populated verdict map MAY be produced from that pass.

#### Scenario: Empty responses survive the retry

- **WHEN** every initial and retry adjudicator response is absent or zero bytes
- **THEN** adjudication fails with attempt diagnostics and produces no synthetic UNCERTAIN verdicts

#### Scenario: Expanded pass has no valid output

- **WHEN** initial valid votes require expanded adjudication and both expanded waves contain no valid output
- **THEN** the entire adjudication stage fails instead of publishing the initial map as a completed outcome

### Requirement: UNCERTAIN always explains uncertainty

Every runtime UNCERTAIN item and every persisted final UNCERTAIN verdict MUST carry a non-empty reason. Omitted candidates, unsupported rejections coerced to UNCERTAIN, and no-majority votes MUST receive explicit machine-generated reasons when a valid model reason is unavailable.

#### Scenario: Adjudicator emits an empty UNCERTAIN reason

- **WHEN** an adjudication response contains an UNCERTAIN item whose reason is empty or whitespace-only
- **THEN** strict schema validation marks that response invalid

#### Scenario: Valid response omits a candidate

- **WHEN** a valid response omits one supplied candidate
- **THEN** its UNCERTAIN vote carries a non-empty omission reason

### Requirement: Every adjudication variant obeys the configured locale

Every ordinary, expanded-context, retry, and stack-presence adjudication prompt MUST require every explanatory title, body, reason, and recommendation to use the resolved locale language. It MUST preserve identifiers, enums, paths, symbol names, and quoted source verbatim and prohibit following language cues in diffs, PR descriptions, lanes, or evidence. Locale enforcement MUST NOT change voting, escalation, evidence, or presence semantics.

#### Scenario: Expanded stack presence uses Korean

- **WHEN** a stack presence check expands context or retries with locale ko
- **THEN** the prompt retains the Korean explanatory-language contract and verbatim evidence contract
