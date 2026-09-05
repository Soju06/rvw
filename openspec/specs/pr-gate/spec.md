# pr-gate

## Purpose

Define anchored pull-request checkout, single review execution, exact coverage and disposition validation, owner-only blocker acceptance, and fail-closed gate artifacts and exits.

## Requirements

### Requirement: Target gate anchors one disposable review

The `rvw gate --target <pr>` command MUST accept only a pull-request target, MUST capture its base and head SHA, MUST provision a disposable checkout detached at that head with both commits resolvable, MUST verify the checkout's HEAD equals the captured head and its porcelain status is empty, MUST verify `git diff <base>...<head>` is computable inside it, and MUST execute the shared review pipeline exactly once in that checkout. Checkout verification failures MUST be fail-closed and carry a machine-readable reason.

#### Scenario: Checkout does not match PR head

- **WHEN** the provisioned checkout resolves to a commit other than the captured head or has tracked or untracked changes
- **THEN** gate fails closed before executing review with a checkout-verification reason

#### Scenario: Base cannot be resolved

- **WHEN** the captured base commit is unavailable in the provisioned checkout
- **THEN** gate fails closed before executing review with reason `base-unresolvable`

#### Scenario: Target review starts

- **WHEN** checkout HEAD, cleanliness, commit resolution, and three-dot diff validations pass
- **THEN** gate invokes one review pipeline and persists its ordinary stage artifacts under one run ID

### Requirement: Target gate defaults to one replica

The `rvw gate --target <pr>` command MUST execute its shared review pipeline with one discovery replica and three adjudication replicas by default. It MUST preserve explicit positive `--replicas` and `--adjudicate-replicas` values independently, MUST record both values in its gate plan while retaining `replicas` as the discovery count, and MUST validate coverage against discovery replicas only.

#### Scenario: Target gate uses its split defaults

- **WHEN** `rvw gate --target <pr>` is invoked without replica overrides
- **THEN** its gate plan records `replicas: 1` and `adjudicate_replicas: 3`, and its shared review pipeline receives those counts for the corresponding stages

#### Scenario: Target gate explicitly requests split replication

- **WHEN** `rvw gate --target <pr> --replicas 2 --adjudicate-replicas 1` is invoked
- **THEN** its gate plan records two discovery replicas and one adjudication replica, and coverage expects only the two discovery replica identities per lane and chunk

### Requirement: Resume never repeats review

The `rvw gate --run <run-id>` mode MUST load the run's persisted artifacts and MUST NOT execute discovery, merge, or adjudication again. The CLI MUST reject an invocation that supplies both or neither of `--target` and `--run`. Every newly persisted gate verdict MUST carry a typed `kind` of `pause`, `failure`, or `completed`. When loading a legacy artifact without `kind`, gate MUST infer `pause` when the failures contain the actionable-dispositions pause marker, `completed` when findings are nonempty, and `failure` otherwise. A resume probe that finds malformed JSON or a schema-invalid verdict artifact MUST exit 3 with machine-readable reason `verdict_artifact_corrupt` and MUST leave the damaged artifact untouched. Before inheritance matching or disposition generation or validation, resume MUST preserve an existing `completed` verdict and exit 2 with machine-readable reason `verdict_already_completed`, except that `--execute` with neither `--dispositions` nor `--inherit` MUST publish that existing verdict without rewriting it. This publication-only resume MUST branch before gate revalidation or any verdict-saving failure path, MUST be strictly read-render-publish apart from publication-status bookkeeping, and MUST render its publish body from the completed JSON verdict as the source of truth. It MUST inspect any `gate-verdict.md` cache through the pinned run descriptor with final-component no-follow and regular-file checks, MUST reject a symlinked or non-regular cache without reading or publishing it, and MUST use the JSON-derived render when the cache is missing or differs. Verdicts of kind `pause` and `failure` MUST remain retryable and replaceable. Target mode and resume of an existing pause verdict MUST retain the ordinary template-and-pause behavior.

#### Scenario: Operator supplies generated dispositions

- **WHEN** an operator resumes a run with a disposition file
- **THEN** gate validates and renders that run without a second review invocation

#### Scenario: Resume names a run with completed evidence

- **WHEN** resume finds an existing completed verdict and requests disposition or inheritance processing
- **THEN** gate exits 2 with reason `verdict_already_completed` and leaves the verdict artifact byte-for-byte unchanged

#### Scenario: Completed dry run is explicitly published

- **WHEN** resume finds an existing completed verdict and supplies `--execute` without `--dispositions` or `--inherit`
- **THEN** gate publishes that existing verdict without regenerating dispositions or rewriting verdict evidence

#### Scenario: Completed Markdown cache is missing or stale

- **WHEN** publication-only resume finds no Markdown cache or finds regular-file bytes that differ from a fresh render of the completed JSON verdict
- **THEN** gate publishes the fresh JSON-derived render and never publishes the missing or stale cache bytes

#### Scenario: Completed Markdown cache is a symlink

- **WHEN** publication-only resume finds a symlinked `gate-verdict.md`
- **THEN** gate rejects the cache without following it and does not attempt publication

#### Scenario: Corrected failure is resumed

- **WHEN** a prior attempt persisted a verdict of kind `failure`
- **THEN** resume retries the run and may overwrite the failure verdict with the new outcome

#### Scenario: Resume verdict artifact is corrupt

- **WHEN** the completed-verdict probe reads truncated JSON or a schema-invalid `gate-verdict.json`
- **THEN** gate exits 3 with reason `verdict_artifact_corrupt` and leaves the artifact byte-for-byte unchanged

### Requirement: Gate rejects stale pull-request anchors

Except for the completed-verdict publication-only resume defined above, after target-mode review and before every resume or publication, gate MUST requery the pull request and MUST fail closed unless it remains open and unmerged with both base and head SHAs equal to the persisted anchors.

#### Scenario: PR head moves during review

- **WHEN** the re-queried head SHA differs from the captured head SHA
- **THEN** gate records a stale-anchor failure, does not publish, and exits nonzero

#### Scenario: PR base moves during review

- **WHEN** the re-queried base SHA differs from the captured base SHA
- **THEN** gate records a stale-anchor failure even if the head SHA is unchanged

### Requirement: Coverage exactly matches the activated plan

Gate MUST require a nonempty activated lane plan with a positive inline chunk count or one agentic scope, MUST derive every planned `(lane, discovery replica, chunk)` combination, MUST require exact equality with the distinct persisted planned coverage run entries, and MUST require every planned entry to be VALID. It MUST reject missing, duplicate, unexpected, invalid, or aggregate-inconsistent planned coverage and MUST NOT use the adjudication replica count for discovery coverage. Informational agentic `uncovered` receipts MUST remain visible in gate artifacts without inventing additional planned identities.

#### Scenario: Vacuous run has no dispatches

- **WHEN** discovery contains no coverage rows or a lane reports zero dispatched runs
- **THEN** gate fails coverage and cannot publish

#### Scenario: One planned lane is absent

- **WHEN** the activated plan contains a lane absent from discovery coverage
- **THEN** gate fails even if aggregate valid and dispatched counts are equal

#### Scenario: One inline chunk combination is missing

- **WHEN** a planned inline lane-replica-chunk entry is absent while another entry is duplicated or aggregate counts otherwise appear complete
- **THEN** gate fails exact coverage comparison

#### Scenario: One planned result is invalid

- **WHEN** every planned combination is present but one entry is INVALID
- **THEN** gate fails with that lane, replica, chunk, and machine-readable invalid reason in persisted coverage

#### Scenario: Agentic receipt remains uncovered

- **WHEN** planned agentic runs are valid but bounded receipt verification leaves a hunk uncovered
- **THEN** exact execution coverage remains structurally valid and the uncovered hunk remains visible in the gate evidence

### Requirement: Actionable dispositions use exact public finding IDs

Gate MUST classify CONFIRMED and UNCERTAIN groups as actionable, MUST require exactly one strict disposition record for every actionable public finding ID, and MUST reject duplicate, omitted, unknown, or REJECTED-group IDs. Each disposition MUST contain one of `accepted` or `must_fix` and a nonblank human-authored reason. A disposition record MAY carry an `inherited_from` run identifier, and records without it MUST remain valid. When `inherited_from` is present, gate MUST reject the document with machine-readable reason `inherited_from_unbound` unless the named run is the selected `--inherit` source and a matcher recomputed from that source carried or prefilled the finding.

#### Scenario: Duplicate record masks an omission

- **WHEN** a disposition file repeats one finding ID and omits another actionable finding ID
- **THEN** gate rejects the file rather than accepting equal aggregate counts

#### Scenario: No disposition file is available

- **WHEN** a completed review has actionable findings, no disposition file is supplied, and the findings are not fully covered by inherited acceptances
- **THEN** gate writes a keyed disposition template for that run and exits nonzero without rerunning review

#### Scenario: Hand-authored provenance is not bound to a source

- **WHEN** a disposition record names an inherited run but the invocation has no matching `--inherit` source or the recomputed matcher left that finding unmatched
- **THEN** gate rejects the document with machine-readable reason `inherited_from_unbound`

### Requirement: Fresh PR gates automatically select prior dispositions

When `rvw gate --target <pr>` is invoked without `--inherit`, without `--no-inherit`, and without `--run`, gate MUST search the configured output root for the most recent prior gate run of the same repository and pull-request number that records validated completed dispositions. It MUST select the qualifying candidate with the latest run-ID timestamp, MUST announce the selected run identifier, and MUST process it through the same validation, matching, summary, and provenance behavior as explicit inheritance.

Gate MUST exclude the current run, non-pull-request targets, runs for another repository or pull-request number, and runs without validated completed dispositions. Repository identity comparison MUST be case-insensitive. A newer nonqualifying candidate MUST NOT prevent selection of an older qualifying candidate.

Candidate discovery MUST accept only directory names that fully match the canonical PR run-identifier grammar owned by the run store; names carrying extra suffix or prefix characters MUST NOT qualify, reach output, or reach provenance. A read failure on one candidate MUST be skipped and MUST NOT abort the scan or the completed review. Discovery MUST report rejected candidates with machine-readable reasons in its informational output, and a scan-level failure of the output root itself MUST be announced distinctly from the absence of qualifying runs before proceeding without inheritance.

#### Scenario: Most recent qualifying run is surrounded by decoys

- **WHEN** the output root contains a qualifying same-repository and same-PR completed run plus newer runs for another PR, another repository, a commit target, and a run without dispositions
- **THEN** gate selects the most recent qualifying same-PR run and records its identifier through the existing inheritance provenance

#### Scenario: No qualifying prior run exists

- **WHEN** fresh target mode finds no prior same-repository and same-PR run with validated completed dispositions
- **THEN** gate emits one informational line and proceeds without inheritance or an error

#### Scenario: Suffixed run directory name does not qualify

- **WHEN** the output root contains an entry whose name extends a canonical PR run identifier with additional safe characters
- **THEN** discovery rejects the entry and its name never appears as a selected identifier

#### Scenario: One unreadable candidate does not abort discovery

- **WHEN** opening a newer candidate raises a filesystem permission error while an older qualifying run exists
- **THEN** gate skips the unreadable candidate, reports it with the skip reasons, and selects the older qualifying run

#### Scenario: Output-root scan failure is announced distinctly

- **WHEN** enumerating the output root itself fails
- **THEN** gate announces the scan failure with its error class and proceeds without inheritance

#### Scenario: Automatic selection cannot choose the current run

- **WHEN** the newly allocated run is visible below the output root during discovery
- **THEN** gate excludes that run identifier from candidate selection

### Requirement: Gate inheritance selection has explicit precedence and opt-out

The `rvw gate` command MUST accept `--no-inherit` to disable automatic source discovery. An explicit `--inherit <run-id>` MUST be used instead of automatic discovery, and supplying `--inherit` together with `--no-inherit` MUST be rejected as an invalid invocation with a clear message and nonzero exit. Resume mode MUST NOT perform automatic discovery.

#### Scenario: Automatic inheritance is disabled

- **WHEN** fresh target mode is invoked with `--no-inherit` while a qualifying prior run exists
- **THEN** gate performs no automatic discovery and proceeds without an inherited source

#### Scenario: Explicit source wins

- **WHEN** fresh target mode supplies `--inherit <run-id>` while a newer qualifying source exists
- **THEN** gate uses the explicitly named run and does not replace it through automatic discovery

#### Scenario: Conflicting selection options are supplied

- **WHEN** an invocation supplies both `--inherit <run-id>` and `--no-inherit`
- **THEN** gate exits nonzero with a clear usage error before inheritance processing

### Requirement: Inheritance loads only a validated same-PR verdict

The `rvw gate` command MUST accept an `--inherit <run-id>` option in target and resume modes, MUST load the inherited run's persisted gate verdict artifact as the sole carry source, and MUST fail closed with a usage error before writing any template when that run is missing, lacks a verdict artifact, or is anchored to a different repository or pull-request number. Repository-slug identity comparisons MUST be case-insensitive while pull-request numbers remain exact. Identity mismatch details MUST name the differing `repo`, `pr_number`, or `run_id` field and include its expected and observed identifier values. Artifact-derived observed string values MUST pass through bounded credential redaction and control removal before interpolation, while trusted current-target expected values MUST remain verbatim. Run lookup MUST accept only identifiers matching `^[A-Za-z0-9._-]+$`, excluding `.` and `..`, and MUST reject path separators, control or Markdown-active characters, symlinked run entries, and any resolved path outside the configured output root before filesystem lookup. `RunStore.open` MUST pin the validated run directory with a no-follow directory descriptor. The source `target.json` and `gate-verdict.json` MUST each be opened relative to that descriptor with final-component no-follow semantics, verified as a regular file from the opened artifact descriptor, and read from that same descriptor. Resume mode MUST reject equal `--run` and `--inherit` identifiers with machine-readable reason `inherit_self_reference` before loading either run. A source verdict's counts MUST contain exactly the keys `CONFIRMED`, `REJECTED`, and `UNCERTAIN` with integer values, and every accepted source finding MUST have a nonblank reason; violations MUST fail with machine-readable reason `inherit_verdict_invalid`. Source-target and source-verdict validation diagnostics MUST pass through the bounded secret-redaction helper before reaching stderr. After legacy inference, the source verdict kind MUST be `completed`; a `pause` or `failure` source MUST fail with machine-readable reason `inherit_source_incomplete` even when it contains accepted finding records. A completed source with zero actionable counts and zero findings MUST remain valid. A completed BLOCK verdict MUST be accepted as a source, and all of its findings MUST remain available to ambiguity counting while only its `accepted` records are eligible to carry or prefill.

#### Scenario: Inherited run belongs to another pull request

- **WHEN** `--inherit` names a run whose persisted target is a different repository or PR number
- **THEN** gate exits with a usage error and writes no template

#### Scenario: Inherited run never reached a verdict

- **WHEN** `--inherit` names a run directory that has stage artifacts but no gate verdict artifact
- **THEN** gate exits with a usage error identifying the missing artifact

#### Scenario: Inherited run ID attempts to escape the output root

- **WHEN** `--inherit` contains a path separator or dot component or resolves through a symlinked run entry
- **THEN** gate exits with machine-readable reason `inherit_run_invalid` before loading any artifact outside the output root

#### Scenario: Inheritance artifact is a symlink

- **WHEN** an otherwise valid source run has a symlinked `target.json` or `gate-verdict.json`
- **THEN** gate rejects the source before reading the linked file

#### Scenario: Inherited verdict has malformed trust-boundary fields

- **WHEN** source counts omit or add a verdict key, contain a non-integer value, or an accepted source finding has a blank reason
- **THEN** gate exits 2 with reason `inherit_verdict_invalid`

#### Scenario: Resume attempts self-inheritance

- **WHEN** `--run A --inherit A` is requested
- **THEN** gate exits 2 with reason `inherit_self_reference` before loading or rewriting run A

#### Scenario: Source is not completed

- **WHEN** a source verdict has kind `pause` or `failure`, including an artifact that contains accepted finding records
- **THEN** gate exits 2 with reason `inherit_source_incomplete` and directs the operator to complete the source first

### Requirement: Accepted dispositions carry by tiered identity matching

For each actionable finding of the current run, gate MUST persist optional `hunk_sha256` and `body_sha256` values computed respectively from the run's canonical unified-diff hunk text and the complete, order-insensitive set of collapsed finding bodies. The canonical hunk parser MUST recognize LF (`\n`) as the only diff line delimiter; U+0085, U+2028, U+2029, and other Unicode line separators inside patch content MUST remain within one diff line. The body digest MUST be SHA-256 over the concatenation, in sorted-body order, of each body's raw 32-byte SHA-256 digest. Gate MUST fail with a gate invariant when an actionable collapsed finding has no bodies, and inheritance-matching or template-generation invariants MUST persist a run-correlated BLOCK verdict unless resume has already rejected an existing completed verdict. Gate MUST require the adjudication outcome verdict keys to equal the merged finding keys exactly before matching. Gate MUST evaluate inherited and current `(file, rule_id)` multiplicity before exact-ID matching, and any pair duplicated on either side MUST remain blank even when IDs and digests match. On an unambiguous pair, gate MUST auto-carry the accepted decision and reason only when the public finding ID exactly matches an `accepted` inherited finding, the source and current `(file, rule_id)` pairs are equal, severity is equal, and both findings have equal known hunk and body-set digests. An exact-ID pair mismatch MUST remain blank with `identity_mismatch` and MUST NOT fall through to tier-two prefill. An exact-ID digest mismatch, severity mismatch, or missing source or current digest MUST be demoted to tier-two handling and MUST NOT auto-carry.

When exact carry is unavailable but one accepted inherited finding and one current actionable finding form a unique `(file, rule_id)` pair, the current severity equals the source severity, and the severity is not `blocker`, gate MUST generate decision `accepted`, copy the prior reason, stamp the inherited run ID, classify the match as `unique_pair_sticky`, and retain the applicable machine-readable demotion reason. A sticky match MUST NOT qualify for automatic continuation and MUST require operator review of the generated disposition template. When the unique pair is a blocker or its severity changed, gate MUST keep decision `must_fix`, MAY prefill the prior reason, MUST NOT classify the match as sticky, and MUST record the applicable demotion reason. Ambiguity counts MUST include inherited `accepted` and `must_fix` findings. Gate MUST NOT carry or sticky-prefill inherited `must_fix` dispositions. Gate MUST stamp every carried, sticky, or reason-only prefilled record with the inherited run's identifier. Each persisted verdict finding MUST optionally record its inheritance tier and blank or demotion reason, and inheritance-summary reason keys MUST use the closed `InheritanceBlankReason` vocabulary.

Every non-carried match result MUST expose a machine-readable `blank_reason` that distinguishes a changed finding ID, an exact-ID source/current pair mismatch (`identity_mismatch`), unmatched findings, prior `must_fix` findings, source-side pair ambiguity, current-side pair ambiguity, changed severity (`severity_changed`), changed hunk content (`content_changed`), missing source digest (`source_digest_missing`), missing current digest (`current_digest_missing`), and changed body diagnosis (`diagnosis_changed`). Generated disposition templates MUST render the applicable reason as a YAML comment beside each affected entry and MUST render the sticky tier and source run beside each sticky entry.

#### Scenario: Exact finding recurs after an unrelated push

- **WHEN** a new run re-detects an accepted finding with the same public finding ID, equal `(file, rule_id)` pair and severity, and equal known canonical hunk and complete body-set digests
- **THEN** the generated record contains the accepted decision, the prior reason, and the inherited run ID

#### Scenario: Exact finding ID has a different identity pair

- **WHEN** an accepted source finding has the current public finding ID but a different file or rule ID
- **THEN** gate leaves the current record blank with `identity_mismatch` and neither carries nor prefills it

#### Scenario: Exact finding ID has changed hunk content

- **WHEN** a public finding ID equals an accepted inherited finding but the known hunk digests differ
- **THEN** gate applies tier-two rules, records `blank_reason: content_changed`, and does not auto-proceed

#### Scenario: Prior verdict has no hunk digest

- **WHEN** an exact-ID inherited finding has no `hunk_sha256`
- **THEN** gate records `source_digest_missing` and applies tier-two rules rather than auto-carrying

#### Scenario: Current finding has no hunk digest

- **WHEN** an exact-ID current finding has no canonical hunk digest
- **THEN** gate records `current_digest_missing` and applies tier-two rules rather than auto-carrying

#### Scenario: Exact finding has a changed diagnosis

- **WHEN** an exact-ID finding has equal known hunk digests but any member of its collapsed body set changes
- **THEN** gate records `diagnosis_changed`, applies tier-two handling, and does not auto-carry

#### Scenario: Exact finding has changed severity

- **WHEN** an exact-ID finding has equal digests but its current severity differs from the source severity
- **THEN** gate records `severity_changed`, prefills through tier two, and does not auto-carry

#### Scenario: Outcome contains an orphan finding key

- **WHEN** an adjudication outcome contains a verdict key absent from the merged finding groups
- **THEN** gate persists a BLOCK gate-invariant verdict naming the orphan key and does not auto-proceed

#### Scenario: Finding bodies recur in another order

- **WHEN** an exact-ID finding has equal known hunk digests and the same nonempty collapsed body set in a different order
- **THEN** the body digest remains equal and the finding remains eligible for tier-one carry

#### Scenario: Collapsed finding has no bodies

- **WHEN** an actionable collapsed finding has an empty body collection
- **THEN** gate raises a gate invariant instead of assigning an ordinary digest

#### Scenario: Prior must-fix finding recurs

- **WHEN** the inherited verdict marked a finding `must_fix` and the new run re-detects the same finding ID
- **THEN** the generated record is a blank `must_fix` template entry without a carried reason and without sticky inheritance

#### Scenario: Same rule moved to a different hunk

- **WHEN** an accepted finding's `(file, rule_id)` pair matches exactly one finding in each run but the finding IDs differ
- **THEN** an equal-severity non-blocker record becomes `accepted` at tier `unique_pair_sticky`, prefills the prior reason, stamps the inherited run ID, and records `finding_id_changed`

#### Scenario: Unique blocker recurs after content changes

- **WHEN** a previously accepted blocker uniquely matches the current blocker by `(file, rule_id)` but does not qualify for exact carry
- **THEN** gate keeps `must_fix`, may prefill the prior reason, and does not classify the record as sticky

#### Scenario: Unique pair changes severity

- **WHEN** a previously accepted finding uniquely matches the current finding by `(file, rule_id)` but their severities differ
- **THEN** gate keeps `must_fix`, records `severity_changed`, and does not classify the record as sticky

#### Scenario: Rule fires twice in one file

- **WHEN** either run contains two findings with the same `(file, rule_id)` pair, including a mixed accepted and must-fix pair in the inherited verdict
- **THEN** no disposition carries or becomes sticky for that pair and the entries remain blank even if one or more public IDs and both digests match exactly

### Requirement: Fully inherited runs proceed without pausing

When every actionable finding of the current run is covered by a hunk-and-body-digest-verified exact-ID carried acceptance, gate MUST persist the generated disposition document under the run directory and MUST continue into disposition validation and verdict construction in the same invocation instead of exiting for a resume round. Sticky accepted entries MUST count as requiring operator completion even though their generated decisions are `accepted`. A partial-inheritance pause MUST report and persist the source run ID plus exact-carried, sticky, reason-only prefilled, and blank counts grouped by machine-readable reason. Owner authorization for accepted blockers MUST be re-verified in the inheriting run, and a failed re-verification MUST persist the finding ID, verified actor, and returned permission. An operational authorization failure MUST persist a BLOCK verdict containing affected blocker IDs, the resolved actor when available, the failed lookup step, and a secret-redacted subprocess diagnostic of at most 500 characters with C0/C1 and Unicode format controls removed by deletion and explicit truncation. Newline placeholders MAY become spaces only after credential redaction. A successful actor or permission subprocess whose trimmed output is empty MUST be classified as the corresponding lookup's operational failure, not as an authorization denial. The diagnostic MUST mask GitHub token prefixes, authorization-header and bearer values, and long base64 or hexadecimal runs before any console or artifact consumer receives it. The verdict artifact MUST render each carried or sticky record's inherited run identifier and inheritance tier.

#### Scenario: Authorization subprocess emits sensitive stderr

- **WHEN** actor or permission lookup fails with stderr containing credentials, control characters, or an oversized response
- **THEN** gate preserves the failed step and exit status while every console, JSON, and Markdown diagnostic contains only the bounded redacted form

#### Scenario: Every actionable finding was previously accepted

- **WHEN** all actionable findings receive tier-one carried acceptances from the inherited verdict
- **THEN** gate validates the persisted generated document and reports a verdict in the same invocation

#### Scenario: One finding is new

- **WHEN** one actionable finding has no match in the inherited verdict
- **THEN** gate writes the partially prefilled template and exits nonzero for human completion

#### Scenario: One finding is sticky

- **WHEN** all other actionable findings exact-carry but one receives `unique_pair_sticky`
- **THEN** gate writes the generated template with sticky provenance and exits for human completion

#### Scenario: Sticky summary is distinct

- **WHEN** inheritance produces exact-carried, sticky, reason-only prefilled, and blank outcomes
- **THEN** the pause summary reports separate counts for all four categories and does not include sticky entries in carried

#### Scenario: Carried blocker acceptance without admin actor

- **WHEN** every actionable finding carries but one accepted blocker's re-verified actor lacks repository admin permission
- **THEN** gate fails closed and does not publish

### Requirement: Publication attempts persist status independently

Every gate publication attempt MUST append one record to the JSON array in `publish-status.json` on success and failure. A legacy single-object artifact MUST load as the first array record. Gate MUST read and write the artifact relative to the pinned run-directory descriptor and MUST open the write target with `O_NOFOLLOW | O_CREAT | O_TRUNC`, rejecting a symlinked existing file. Each record MUST contain `attempted_at`, mode `dry_run` or `execute`, boolean `ok`, a bounded secret-redacted failure `detail` or null on success, and boolean `republish`; successful records MUST also contain the `inline_count` and `body_fallback_count` returned by publication. Publication status MUST remain separate from the immutable completed `GateVerdict` evidence.

#### Scenario: Publication fails

- **WHEN** dry-run payload construction or execute publication raises an operational publication error
- **THEN** gate persists `ok: false` with the attempt mode, republish state, timestamp, and redacted detail before exiting

#### Scenario: Dry-run publication succeeds

- **WHEN** gate successfully constructs its default dry-run publication payload
- **THEN** gate appends `ok: true`, mode `dry_run`, null detail, the applicable republish state, and the inline and body-fallback counts without discarding prior attempts

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

### Requirement: Auto policy resolution is portable and precedence-ordered

Policy-gated `run` and `auto` MUST resolve policy in this order: an explicit policy path; `.rvw/policies/auto.yaml` read from the captured base commit; an existing external `~/.hermes/review/policies/auto.yaml`; and the packaged `rvw/resources/policies/auto-default.yaml`. Selecting the external policy MUST emit a deprecation warning. The packaged default MUST be installed with the Python distribution and available equally to host, Actions, and App. An explicit missing path or malformed selected policy MUST be an invalid configuration and MUST NOT silently fall through to a lower-priority source. The effective source and path MUST be recorded in `process.json`; package fallback MUST NOT require modifying the external registry.

#### Scenario: Base policy and external policy coexist

- **WHEN** the captured base commit contains a policy and no explicit path is supplied
- **THEN** that base policy wins and the process envelope identifies source `repository`

#### Scenario: Fresh host has no policy registry

- **WHEN** no explicit, base-commit, or external policy exists
- **THEN** policy resolution uses the packaged default and records source `package`

#### Scenario: External compatibility policy is used

- **WHEN** only the external policy exists
- **THEN** it wins over the package default, emits a deprecation warning, and records source `external`

#### Scenario: Explicit policy wins

- **WHEN** an explicit valid policy path is supplied alongside repository and external policies
- **THEN** the explicit policy is used and source is `explicit`

#### Scenario: Base policy is malformed

- **WHEN** the captured base commit contains an invalid auto policy
- **THEN** the command exits 2 with a policy configuration failure rather than using another source
