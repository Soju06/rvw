# operation-modes

## Purpose

Define interactive review, deterministic auto policy, lane health gates, packaging, and the boundary between rvw execution mechanics and external executor guidance.
## Requirements
### Requirement: Review and auto share one pipeline

The `review` and `auto` commands MUST use the same target-resolution, DISCOVER, MERGE, optional ADJUDICATE, and REPORT implementation rather than forked stage logic.

#### Scenario: Auto review runs

- **WHEN** `rvw auto` is invoked for a target
- **THEN** it executes the common pipeline and then evaluates the persisted merged groups with an auto policy

### Requirement: Routine review modes default to one replica

The `rvw review` and `rvw auto` commands MUST default to one discovery and adjudication replica, and `rvw plan` MUST report one replica in its payload and calculate default total runs from that count. Review commands that expose `--replicas` MUST accept an explicit positive count and MUST preserve replicated execution when the count is greater than one.

#### Scenario: Review uses its default replica count

- **WHEN** `rvw review` is invoked without `--replicas`
- **THEN** the shared pipeline receives one replica for discovery and adjudication

#### Scenario: Plan reports the routine default

- **WHEN** `rvw plan` renders a plan without a replica override
- **THEN** its payload reports `replicas: 1` and its total run count uses one run per active lane per diff chunk

#### Scenario: Replication is explicitly requested

- **WHEN** a review command is invoked with `--replicas 3`
- **THEN** the shared pipeline receives three replicas without changing dispatch, retry, widening, or voting behavior

### Requirement: Runtime-executing commands expose bounded concurrency

The `review`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--concurrency` with a default of 8, MUST reject values below 1 before runtime execution, and MUST propagate an explicit positive value to every discovery, adjudication, sampling, and stack-presence runtime wave they start.

#### Scenario: Review uses default concurrency

- **WHEN** `rvw review` is invoked without `--concurrency`
- **THEN** discovery and adjudication each receive a concurrency capacity of 8

#### Scenario: Operator lowers concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 3`
- **THEN** every runtime wave started by that command uses capacity 3 without changing replica counts

#### Scenario: Operator supplies zero concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 0`
- **THEN** CLI validation rejects the invocation before any runtime work starts

### Requirement: Pause stops after MERGE

The `review --pause` mode MUST persist target, discovery, and merge artifacts, MUST stop immediately after MERGE, and MUST perform neither adjudication, report generation, nor publication.

#### Scenario: Operator pauses a review

- **WHEN** `rvw review --pause` finishes merge
- **THEN** the CLI prints a resume hint using `rvw report --run <run-id>` and returns without later stages

### Requirement: Auto policy is strict YAML

An auto policy MUST strictly define `promote_to_blocker`, `drop`, `block_when`, and `publish_state`, and `publish_state` MUST accept only `comment` or `none`.

#### Scenario: Policy attempts approval

- **WHEN** a policy sets `publish_state: approve`
- **THEN** policy validation fails because approval is not expressible

### Requirement: Policy evaluation is deterministic

Policy evaluation MUST exclude REJECTED groups, MUST drop groups matching the configured agreement/severity ceiling, MUST promote eligible non-blockers, and MUST block only groups meeting the configured effective-severity and confirmation rule.

#### Scenario: Confirmed warning is promoted

- **WHEN** a confirmed warning meets the promotion agreement threshold and blocker is the block threshold
- **THEN** its key appears in both promoted and blocking results

#### Scenario: Unresolved group under confirmed-only policy

- **WHEN** a blocker group is unresolved and `confirmed_only: true`
- **THEN** it is considered but does not block

### Requirement: Auto exposes a CI exit contract

The auto command MUST exit 0 for policy verdict PASS and MUST exit 1 for policy verdict BLOCK.

#### Scenario: Blocking keys exist

- **WHEN** deterministic evaluation returns BLOCK
- **THEN** CLI output identifies the verdict and the process exits 1

### Requirement: Approval cannot be emitted

Neither review nor auto mode SHALL emit an approving review, and `--allow-approve` MUST remain a non-enabling placeholder while publication stays COMMENT-only.

#### Scenario: Caller passes allow-approve

- **WHEN** `rvw auto --allow-approve` is invoked
- **THEN** the CLI warns that approval is not implemented and continues without enabling an APPROVE payload

### Requirement: Sampling compares enum and free variants

The sampling gate MUST pass its fixture diff through the shared exclusion and chunk planner, MUST execute closed-enum and free-rule-ID variants with equal replica counts for every chunk in one bounded wave, MUST report sorted free-variant rule IDs absent from the lane's closed enum as `novel_rule_ids`, and MUST report in-enum enum-only and free-only `(file, line)` sites separately as site variance. It MUST retain the `PASS` and `REVIEW` verdict values, MUST report `REVIEW` and exit 1 only when `novel_rule_ids` is nonempty, and MUST otherwise report `PASS` and exit 0 even when site variance exists.

#### Scenario: Free variant invents a rule ID

- **WHEN** any valid free-variant replica on any fixture chunk emits a rule ID outside the lane's generated closed enum
- **THEN** sampling lists that ID in `novel_rule_ids`, reports `REVIEW`, and exits 1

#### Scenario: Replicas find an existing rule at different sites

- **WHEN** free-only or enum-only sites use rule IDs contained in the lane's closed enum and no novel rule ID is emitted
- **THEN** sampling records those sites as variance, reports `PASS`, and exits 0

#### Scenario: Novel rule appears at an enum-covered site

- **WHEN** the free variant emits an out-of-enum rule ID at a `(file, line)` also found by the enum variant
- **THEN** sampling still reports that rule ID as novel because gap detection is independent of site-set difference

#### Scenario: Large fixture uses production chunk semantics

- **WHEN** a sampling fixture exceeds the per-prompt aggregate character budget after exclusions
- **THEN** both variants execute every replica on every planner-produced chunk while one-chunk fixture artifact paths remain unchanged

### Requirement: Doctor reports lane and adjudication health

The doctor command MUST aggregate recent persisted runs into per-lane run count, invalid count, finding count, and `/other` rate plus adjudication group counts, rejection rate, unresolved count, and coerced rejection count when outcomes exist.

#### Scenario: Lane emits other findings

- **WHEN** two of ten stored findings for a lane end in `/other`
- **THEN** doctor reports `other_rate` 0.2 for that lane

### Requirement: Packaging exposes the rvw CLI

The project MUST package as the PyPI distribution `rvw`, MUST require Python 3.12 or newer, and MUST expose the Typer app at the `rvw` console entry point through the uv-managed build.

#### Scenario: Installed package is invoked

- **WHEN** the distribution is installed in a supported Python environment
- **THEN** the `rvw` command resolves to `rvw.cli:app`

### Requirement: Review mechanics stay inside rvw

Review runtime concerns such as strict schemas, replication, deadlines, artifacts, and validity classification MUST live in rvw, while external executor documentation SHALL remain responsible for implementation-task delegation and post-delegation verification.

#### Scenario: Runtime behavior changes

- **WHEN** Codex completion validation or replication behavior changes
- **THEN** the change is made in rvw's runtime/pipeline contract rather than duplicated into lane prompts or external executor profiles

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
