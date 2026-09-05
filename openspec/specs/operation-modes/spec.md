# operation-modes

## Purpose

Define interactive review, deterministic auto policy, lane health gates, packaging, and the boundary between rvw execution mechanics and external executor guidance.

## Requirements

### Requirement: Runtime executions honor the host-global concurrency contract

Runtime-executing commands MUST bound total in-flight runtime executions across all rvw processes on one host with a file-lock slot gate shared through a host-local slot directory, defaulting to 12 slots. The cap MUST be configurable via `RVW_HOST_CONCURRENCY`, where `0` disables the gate and a non-integer or negative value MUST be rejected before runtime execution. Slots MUST be released when the owning execution completes, fails, or its process terminates, and a slot root that is a symlink or foreign-owned MUST fail closed. On cancellation or another exceptional unwind, the entire spawned runtime process group MUST be terminated, with escalation to `SIGKILL` after a bounded grace period, and the wrapper MUST be reaped before its host slot can be released. A `SIGKILL` escalation MUST be recorded in the run log. On Linux, each spawned runtime wrapper MUST request a parent-death `SIGTERM`, applied exec-side by the command wrapper, so a runtime child does not outlive the rvw process whose slot the kernel released. Linux execution MUST fail closed with a clear runtime error when the required `setpriv` executable is unavailable. This child-lifetime coupling is not guaranteed on non-Linux platforms.

The gate MUST require atomic `O_NOFOLLOW` support and fail at construction when it is unavailable. The ambient parent selected from `XDG_RUNTIME_DIR` MUST be validated without changing its permissions or rejecting group and other permission bits, and a relative `XDG_RUNTIME_DIR` value MUST be ignored in favor of the absolute fallback slot root. Each rvw-owned slot directory (`rvw-slots` and `c{cap}`), including a pre-existing directory, MUST be set to mode 0700 and re-verified through its opened descriptor before use. Slot files MUST be opened relative to the validated slot-directory descriptor while that descriptor remains open for acquisition, and descriptor-based validation MUST fail closed if ownership or directory type is unsafe, or if an rvw-owned directory's normalized mode is unsafe.

#### Scenario: Two processes share the host cap

- **GIVEN** `RVW_HOST_CONCURRENCY` is 12 on one host
- **WHEN** two rvw review processes each run with process concurrency 8
- **THEN** their combined in-flight runtime executions never exceed 12

#### Scenario: Operator disables the gate

- **WHEN** a runtime-executing command starts with `RVW_HOST_CONCURRENCY=0`
- **THEN** runtime executions are bounded only by the per-process concurrency

#### Scenario: Invalid cap is rejected

- **WHEN** a runtime-executing command starts with `RVW_HOST_CONCURRENCY=abc`
- **THEN** the command fails with a usage error before any runtime execution

#### Scenario: Killed process frees its slots

- **WHEN** a process holding host slots is terminated without cleanup
- **THEN** its slots become acquirable by other processes without manual intervention

#### Scenario: Killed Linux parent terminates its runtime child

- **GIVEN** an rvw process on Linux has spawned a runtime wrapper while holding a host slot
- **WHEN** the rvw process receives `SIGKILL`
- **THEN** the kernel releases its slot and sends `SIGTERM` to the runtime wrapper so the wrapper and runtime terminate instead of overlapping replacement work

#### Scenario: Cancellation terminates the runtime process tree

- **GIVEN** a runtime wrapper has spawned a runtime child while holding a host slot
- **WHEN** execution is cancelled and the child does not exit during the graceful termination period
- **THEN** the runtime process group is sent `SIGKILL`, the escalation is recorded in the run log, and no process in the group outlives the host slot

#### Scenario: Ambient runtime directory has permissive permissions

- **WHEN** an owner-matched `XDG_RUNTIME_DIR` has group or other permissions
- **THEN** the gate validates it without changing those permissions and remains usable

#### Scenario: Relative runtime directory is ignored

- **WHEN** `XDG_RUNTIME_DIR` is set to a relative path
- **THEN** the gate uses the absolute fallback slot root so all processes on the host share one pool

#### Scenario: Existing rvw-owned slot directory has permissive permissions

- **WHEN** an owner-matched `rvw-slots` or `c{cap}` directory already exists with group or other permissions
- **THEN** the gate sets it to mode 0700 and verifies that mode through the opened directory descriptor before acquiring a slot

#### Scenario: Validated slot directory path is replaced

- **WHEN** a slot acquisition begins after the slot-directory descriptor has been validated
- **THEN** every candidate slot file is opened relative to that held descriptor rather than by re-resolving the validated path

#### Scenario: Atomic symlink protection is unavailable

- **WHEN** the platform does not expose `O_NOFOLLOW`
- **THEN** host-slot gate construction fails with a clear runtime error before any slot path is used

### Requirement: Review and auto share one pipeline

The `review`, `run`, and `auto` commands MUST use the same target-resolution, DISCOVER, MERGE, optional ADJUDICATE, and REPORT implementation. `auto` MUST be a compatibility alias for the policy-gated `run` execution, retaining policy-controlled publication unless an existing publication override is supplied.

#### Scenario: Auto review runs

- **WHEN** `rvw auto` is invoked for a target
- **THEN** it executes the same contract as `rvw run --policy auto` with publication selected by the effective policy or explicit override

### Requirement: Discovery mode is selectable and agentic by default

Runtime-executing review, run, auto, gate, stack-review, and plan paths MUST select `agentic` discovery by default and MUST accept `inline` as an explicit fallback. The selected mode MUST propagate unchanged through planning and discovery. Sampling MUST continue to use the inline fixture path.

#### Scenario: Operator uses the default

- **WHEN** an ordinary review command omits discovery mode
- **THEN** it provisions or verifies a checkout and runs agentic discovery

#### Scenario: Operator selects legacy fallback

- **WHEN** an ordinary review command selects `inline`
- **THEN** the existing embedded-diff, exclusion, budget, and chunk behavior is used without requiring an agentic checkout

#### Scenario: Uncommitted review uses inline mode

- **WHEN** an operator selects inline discovery for an uncommitted target
- **THEN** the existing in-memory target diff remains reviewable

### Requirement: Routine review modes default to one replica

The `rvw review`, `rvw run`, and `rvw auto` commands MUST default to one discovery replica and three adjudication replicas. Commands that expose `--replicas` MUST use it only as the positive discovery replica count, MUST expose an independently positive `--adjudicate-replicas` count, and MUST preserve explicit values for each stage. `rvw plan` MUST report the discovery count as `replicas`, MUST report the adjudication count as `adjudicate_replicas`, and MUST calculate discovery run totals from the discovery count only.

#### Scenario: Review uses split defaults

- **WHEN** `rvw review` is invoked without replica overrides
- **THEN** the shared pipeline receives one discovery replica and three adjudication replicas

#### Scenario: Plan reports split routine defaults

- **WHEN** `rvw plan` renders a plan without replica overrides
- **THEN** its payload reports `replicas: 1` and `adjudicate_replicas: 3`, and its total discovery run count uses one run per active lane per diff chunk

#### Scenario: Discovery replication is explicitly requested

- **WHEN** a review command is invoked with `--replicas 2`
- **THEN** the shared pipeline receives two discovery replicas and the independently selected adjudication count

#### Scenario: Single-vote adjudication is explicitly requested

- **WHEN** a review command is invoked with `--adjudicate-replicas 1`
- **THEN** the shared pipeline preserves one adjudication replica without changing discovery dispatch, retry, widening, or voting rules

#### Scenario: Replica count is invalid

- **WHEN** either replica option is supplied with a value below one
- **THEN** the command rejects the invocation before executing the pipeline

### Requirement: Runtime-executing commands expose bounded concurrency

The `review`, `run`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--concurrency` with a default of 8, MUST reject values below 1 before runtime execution, and MUST propagate an explicit positive value to every discovery, adjudication, sampling, and stack-presence runtime wave they start.

#### Scenario: Review uses default concurrency

- **WHEN** `rvw review` is invoked without `--concurrency`
- **THEN** discovery and adjudication each receive a concurrency capacity of 8

#### Scenario: Operator lowers concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 3`
- **THEN** every runtime wave started by that command uses capacity 3 without changing replica counts

#### Scenario: Operator supplies zero concurrency

- **WHEN** a runtime-executing command is invoked with `--concurrency 0`
- **THEN** CLI validation rejects the invocation before any runtime work starts

### Requirement: Runtime-executing commands expose bounded deadlines

The `review`, `run`, `auto`, `gate`, `stack review`, and `sample` commands MUST expose `--deadline` with a default of 600, MUST reject values below 1 or above 1800 before runtime execution, and MUST propagate a permitted value as the base deadline to every discovery, adjudication, sampling, and stack-presence runtime path they start while preserving the established doubled deadline for an expanded pass.

#### Scenario: Review uses the default deadline

- **WHEN** `rvw review` is invoked without `--deadline`
- **THEN** discovery and adjudication each receive a base deadline of 600 seconds

#### Scenario: Operator raises the deadline to the ceiling

- **WHEN** a runtime-executing command is invoked with `--deadline 1800`
- **THEN** every runtime path started by that command receives 1800 seconds as its base deadline and an expanded pass receives 3600 seconds

#### Scenario: Operator supplies zero deadline

- **WHEN** a runtime-executing command is invoked with `--deadline 0`
- **THEN** CLI validation rejects the invocation before any runtime work starts

#### Scenario: Operator exceeds the deadline ceiling

- **WHEN** a runtime-executing command is invoked with `--deadline 1801`
- **THEN** CLI validation rejects the invocation before any runtime work starts

### Requirement: Pause stops after MERGE

The `review --pause` mode MUST persist target, discovery, and merge artifacts, MUST stop immediately after MERGE, and MUST perform neither adjudication, report generation, nor publication.

#### Scenario: Operator pauses a review

- **WHEN** `rvw review --pause` finishes merge
- **THEN** the CLI prints a resume hint using `rvw report --run <run-id>` and returns without later stages

### Requirement: Existing runs can be re-adjudicated

`rvw adjudicate --run <run-id>` MUST load the run's persisted target, discovery, and merge artifacts, execute adjudication against an explicitly supplied repository checkout, and atomically replace `outcome.json` and `report.md` only after success without executing discovery. Missing required inputs MUST fail with a precise message naming the missing artifact, and failed re-adjudication MUST retain any pre-existing outcome and report.

#### Scenario: Re-adjudication succeeds

- **WHEN** a run contains valid `target.json`, `discover.json`, and `merge.json` and the adjudicator returns valid output
- **THEN** fresh outcome and report artifacts are written while discovery artifacts and runtime calls remain unchanged

#### Scenario: Merge input is missing

- **WHEN** `rvw adjudicate --run` opens a run without `merge.json`
- **THEN** the command fails with an error that names `merge.json` and does not invoke the adjudicator

#### Scenario: Re-adjudication infrastructure fails

- **WHEN** a run already has `outcome.json` and `report.md` and re-adjudication produces no valid response after retry
- **THEN** the command reports the infrastructure failure and leaves both pre-existing artifacts byte-for-byte intact

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

The `run` and `auto` commands MUST reserve exit 0 for policy PASS, 1 for policy BLOCK, 2 for invalid input or configuration, and 3 for infrastructure failure. Invalid targets, anchor mismatches, absent explicitly selected policies, and invalid policy content MUST exit 2. Checkout, runtime, adjudication, publication, and unexpected execution exceptions MUST exit 3 and MUST NOT escape as exit 1. A failed review summary or zero VALID discovery coverage MUST exit 3 with a machine-readable `review_failed:<detail>` reason even when merge and adjudication are empty.

#### Scenario: Blocking keys exist

- **WHEN** successful execution produces a deterministic policy BLOCK
- **THEN** process status is `block` and the command exits 1

#### Scenario: All discovery lanes are invalid

- **WHEN** discovery has no VALID lane and produces no merged findings
- **THEN** the command persists `infra_failed` with exit 3 and `review_failed:<detail>` rather than PASS

#### Scenario: Policy path is missing

- **WHEN** an explicitly selected policy file does not exist
- **THEN** the command persists `invalid` and exits 2

#### Scenario: Adjudication or publication raises

- **WHEN** either stage raises an infrastructure exception
- **THEN** the command preserves available artifacts, persists `infra_failed`, and exits 3

### Requirement: Approval cannot be emitted

Neither review nor auto mode SHALL emit an approving review, and `--allow-approve` MUST remain a non-enabling placeholder while publication stays COMMENT-only.

#### Scenario: Caller passes allow-approve

- **WHEN** `rvw auto --allow-approve` is invoked
- **THEN** the CLI warns that approval is not implemented and continues without enabling an APPROVE payload

### Requirement: Sampling compares enum and free variants

The sampling gate MUST accept both unified-diff fixtures and ordinary source-file fixtures, MUST pass a fixture that starts with a `diff --git ` or `--- ` file header to the shared exclusion and chunk planner without wrapping it in another diff, and MUST convert an ordinary source-file fixture to a `/dev/null` unified diff before planning. It MUST fail before runtime dispatch with a machine-readable `empty-review-diff` user error containing every excluded file's reason when budgeting retains zero review characters. Otherwise, it MUST execute closed-enum and free-rule-ID variants with equal replica counts for every chunk in one bounded wave, MUST report sorted free-variant rule IDs absent from the lane's closed enum as `novel_rule_ids`, and MUST report in-enum enum-only and free-only `(file, line)` sites separately as site variance. It MUST retain the `PASS` and `REVIEW` verdict values, MUST report `REVIEW` and exit 1 only when `novel_rule_ids` is nonempty, and MUST otherwise report `PASS` and exit 0 even when site variance exists.

#### Scenario: Unified diff fixture is sampled directly

- **WHEN** a fixture starts with a supported unified-diff file header and contains multiple file segments
- **THEN** sampling budgets and chunks those original segments without a containing diff-of-diff layer

#### Scenario: Ordinary source file is sampled

- **WHEN** a fixture does not start with a supported unified-diff file header
- **THEN** sampling reviews the unified diff produced by comparing `/dev/null` with that fixture

#### Scenario: Every fixture segment is excluded

- **WHEN** generated-path and oversized-file exclusions leave zero retained fixture characters
- **THEN** sampling dispatches no runtime work, cannot report `PASS`, and exits in the user-error class with error code `empty-review-diff` and the `excluded_reason` mapping

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
The project container MUST install that distribution from repository source, include the
distribution's packaged common lanes, and expose the same console entry point as its
argument-preserving container entry point.

#### Scenario: Installed package is invoked

- **WHEN** the distribution is installed in a supported Python environment
- **THEN** the `rvw` command resolves to `rvw.cli:app`

#### Scenario: Containerized package is invoked

- **WHEN** a caller starts the project image with `auto --target <sha> --repo-dir <checkout>`
- **THEN** the image invokes the installed `rvw` console entry point with those arguments and packaged common lanes available

### Requirement: CI composition preserves auto and publication semantics

Containerized GitHub Actions and App invocations MUST call `rvw run` and consume its canonical process and summary artifacts. They MUST preserve the reserved exit categories and COMMENT-only publication behavior, MUST NOT convert BLOCK or failed execution to success, and MUST NOT use stdout prose to determine the result.

#### Scenario: CI auto finds policy blockers

- **WHEN** containerized evaluation returns BLOCK and publishes finding narratives
- **THEN** the workflow job fails from exit 1 and the published review remains a COMMENT

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

### Requirement: Run is the shared policy-gated execution entry

`rvw run` MUST accept `--target <pr-url|pr-number|sha>`, optional `--base-ref` and `--head-ref`, optional `--repo-dir`, `--out`, `--policy auto|PATH`, `--publish none|github-comment`, and `--json`. It MUST expose positive discovery and adjudication replica controls with defaults 1 and 3, positive concurrency default 8, per-execution deadline default 600 seconds restricted to 1 through 1800, and discovery mode `agentic|inline` defaulting to `agentic`. It MUST execute the existing shared pipeline once, evaluate policy only after checking execution status, and record effective settings. `--out DIR` MUST name the artifact directory itself, with no appended run ID; without it the ordinary `/tmp/rvw/<run-id>` root MUST remain available. The run ID MUST remain recorded independently of the output path.

#### Scenario: Caller chooses an artifact directory

- **WHEN** `rvw run --out /workspace/result` completes
- **THEN** the process, summary, stage files, and runtime evidence are written beneath `/workspace/result` and its process contract still records the run ID

#### Scenario: Host caller supplies no checkout

- **WHEN** an agentic `run` invocation omits `--repo-dir`
- **THEN** existing provisioning supplies a verified checkout for shared discovery and adjudication

### Requirement: Run verifies supplied target anchors

For each supplied `--base-ref` or `--head-ref`, `run` and its alias MUST compare the resolved target SHA with the supplied SHA before review or publication. Any mismatch MUST return exit 2, status `invalid`, and failure code `target_anchor_mismatch` with expected and observed anchor detail. Without supplied anchors the commands MUST resolve the target through the ordinary resolver. Actions and App MUST supply both captured event anchors.

#### Scenario: PR head advances after the event

- **WHEN** resolved PR head differs from the event head passed through `--head-ref`
- **THEN** review and publication do not start and the process contract records `target_anchor_mismatch`

#### Scenario: PR base advances after the event

- **WHEN** resolved PR base differs from the supplied `--base-ref`
- **THEN** execution fails with the same invalid-input classification even when head is unchanged

### Requirement: PR URLs bind all GitHub operations to the target repository

When target resolution receives a PR URL, Python MUST bind subsequent GitHub PR metadata, diff, changed-file, and REST operations to the owner/repository in that URL through explicit repository arguments, repository-qualified REST paths, or a Python-owned subprocess environment. Ambient checkout identity or `GH_REPO` MUST NOT redirect those calls.

#### Scenario: Caller is in an unrelated checkout

- **WHEN** a PR URL names `owner/base` while cwd or ambient `GH_REPO` names another repository
- **THEN** every resulting GitHub PR operation remains bound to `owner/base`
