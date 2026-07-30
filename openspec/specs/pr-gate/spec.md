# pr-gate

## Purpose

Define anchored pull-request checkout, single review execution, exact coverage and disposition validation, owner-only blocker acceptance, and fail-closed gate artifacts and exits.

## Requirements

### Requirement: Target gate anchors one disposable review

The `rvw gate --target <pr>` command MUST accept only a pull-request target, MUST capture its base and head SHA, MUST provision a disposable checkout detached at that head, MUST verify the checkout's HEAD equals the captured head and its porcelain status is empty, and MUST execute the shared review pipeline exactly once in that checkout.

#### Scenario: Checkout does not match PR head

- **WHEN** the provisioned checkout resolves to a commit other than the captured head or has tracked or untracked changes
- **THEN** gate fails closed before executing review

#### Scenario: Target review starts

- **WHEN** the checkout and anchor validations pass
- **THEN** gate invokes one review pipeline and persists its ordinary stage artifacts under one run ID

### Requirement: Target gate defaults to one replica

The `rvw gate --target <pr>` command MUST execute its shared review pipeline with one replica by default and MUST preserve an explicit positive `--replicas` count for opt-in replicated verification.

#### Scenario: Target gate uses its default replica count

- **WHEN** `rvw gate --target <pr>` is invoked without `--replicas`
- **THEN** its gate plan records one replica and its shared review pipeline receives one replica

#### Scenario: Target gate explicitly requests replication

- **WHEN** `rvw gate --target <pr> --replicas 3` is invoked
- **THEN** its gate plan records three replicas and its shared review pipeline receives three replicas

### Requirement: Resume never repeats review

The `rvw gate --run <run-id>` mode MUST load the run's persisted artifacts and MUST NOT execute discovery, merge, or adjudication again. The CLI MUST reject an invocation that supplies both or neither of `--target` and `--run`.

#### Scenario: Operator supplies generated dispositions

- **WHEN** an operator resumes a run with a disposition file
- **THEN** gate validates and renders that run without a second review invocation

### Requirement: Gate rejects stale pull-request anchors

After target-mode review and before every resume or publication, gate MUST requery the pull request and MUST fail closed unless it remains open and unmerged with both base and head SHAs equal to the persisted anchors.

#### Scenario: PR head moves during review

- **WHEN** the re-queried head SHA differs from the captured head SHA
- **THEN** gate records a stale-anchor failure, does not publish, and exits nonzero

#### Scenario: PR base moves during review

- **WHEN** the re-queried base SHA differs from the captured base SHA
- **THEN** gate records a stale-anchor failure even if the head SHA is unchanged

### Requirement: Coverage exactly matches the activated plan

Gate MUST require a nonempty activated lane plan with a positive chunk count, MUST derive every planned `(lane, replica, chunk)` combination, MUST require exact equality with the distinct persisted coverage run entries, and MUST require every planned entry to be VALID. It MUST reject missing, duplicate, unexpected, invalid, or aggregate-inconsistent coverage.

#### Scenario: Vacuous run has no dispatches

- **WHEN** discovery contains no coverage rows or a lane reports zero dispatched runs
- **THEN** gate fails coverage and cannot publish

#### Scenario: One planned lane is absent

- **WHEN** the activated plan contains a lane absent from discovery coverage
- **THEN** gate fails even if aggregate valid and dispatched counts are equal

#### Scenario: One chunk combination is missing

- **WHEN** a planned lane-replica-chunk entry is absent while another entry is duplicated or aggregate counts otherwise appear complete
- **THEN** gate fails exact coverage comparison

#### Scenario: One chunk result is invalid

- **WHEN** every planned combination is present but one chunk entry is INVALID
- **THEN** gate fails with that lane, replica, chunk, and machine-readable invalid reason in persisted coverage

### Requirement: Actionable dispositions use exact public finding IDs

Gate MUST classify CONFIRMED and UNCERTAIN groups as actionable, MUST require exactly one strict disposition record for every actionable public finding ID, and MUST reject duplicate, omitted, unknown, or REJECTED-group IDs. Each disposition MUST contain one of `accepted` or `must_fix` and a nonblank human-authored reason.

#### Scenario: Duplicate record masks an omission

- **WHEN** a disposition file repeats one finding ID and omits another actionable finding ID
- **THEN** gate rejects the file rather than accepting equal aggregate counts

#### Scenario: No disposition file is available

- **WHEN** a completed review has actionable findings and no disposition file is supplied
- **THEN** gate writes a keyed disposition template for that run and exits nonzero without rerunning review

### Requirement: Blocker acceptance is owner-only and explicit

Gate MUST allow an `accepted` blocker to pass disposition validation only when its reason is nonblank and the authenticated GitHub actor has repository `admin` permission. rvw MUST record the verified actor, MUST NOT generate the reason, and MUST NOT translate acceptance into GitHub approval.

#### Scenario: Non-owner accepts a blocker

- **WHEN** an authenticated actor without repository admin permission marks a blocker `accepted`
- **THEN** gate fails closed and does not publish

#### Scenario: Owner records blocker acceptance

- **WHEN** a repository admin supplies a nonblank acceptance reason for a blocker
- **THEN** gate records the actor and reason while publication remains a COMMENT

### Requirement: Gate verdict and exit are fail-closed

Gate MUST write a reconstructable verdict artifact after artifact-backed validation, MUST report `PASS` only when anchors, checkout, coverage, dispositions, and owner checks pass and no disposition is `must_fix`, and MUST otherwise report `BLOCK`. The command MUST exit 0 for PASS, 1 for BLOCK or a failed gate invariant, 2 for invalid invocation or disposition syntax, and 3 for checkout, GitHub, or other operational failure.

#### Scenario: Finding is marked must-fix

- **WHEN** every actionable ID is present but one disposition is `must_fix`
- **THEN** the verdict identifies that finding, reports BLOCK, and exits 1

#### Scenario: Accepted findings satisfy all invariants

- **WHEN** every actionable finding is accepted, every blocker acceptance is owner-authorized, and anchors and coverage pass
- **THEN** gate reports PASS and exits 0
