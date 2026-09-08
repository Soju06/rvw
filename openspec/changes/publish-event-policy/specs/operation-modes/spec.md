## ADDED Requirements

### Requirement: Publish event override is downgrade-only

`rvw publish --run <id>` MUST accept `--event comment|request_changes|approve`. The command MUST re-evaluate the auto policy verdict from the persisted merge and outcome, select the event from the repository `publish` policy, and accept the override only when it names the selected event or downgrades REQUEST_CHANGES or APPROVE to COMMENT, recording `event_clamped_reason: event_override`. Any override above the selected event MUST exit 2 with machine-readable reason `event_override_exceeds_policy` before any GitHub write. Dry runs MUST print the selected event, its policy source, and the planned thread and dismissal actions.

#### Scenario: Operator downgrades

- **WHEN** the policy selects REQUEST_CHANGES and the operator passes `--event comment`
- **THEN** the review is published as COMMENT and the recorded clamp reason is `event_override`

#### Scenario: Operator tries to escalate

- **WHEN** the policy selects COMMENT and the operator passes `--event request_changes`
- **THEN** the command exits 2 with `event_override_exceeds_policy` and nothing is written

## MODIFIED Requirements

### Requirement: Auto policy is strict YAML

An auto policy MUST strictly define `promote_to_blocker`, `drop`, `block_when`, and `publish_state`. It MUST accept optional boolean `allow_language_fallback` defaulting to false. The `publish_state` field MUST accept only `comment` or `none` and MUST keep deciding whether the policy-gated commands publish at all. The policy MUST accept an optional strict `publish` block (`on_block`: `comment` or `request_changes`; `on_pass`: `comment`, `approve`, or `none`; boolean `dismiss_on_pass`; boolean `approve_requires_explicit_opt_in` defaulting to true) and an optional strict `threads` block (boolean `resolve_on_fix` and `reuse_open_thread`, both defaulting to true). A fault inside either block MUST be reported as `publish_policy_invalid` (exit 2, status `invalid`) with `approve_not_opted_in` as the detail when `on_pass: approve` lacks `approve_requires_explicit_opt_in: false`; faults elsewhere in the policy MUST keep the existing `invalid_policy` classification, at publication sites as well. The deprecated external policy file MAY still decide `publish_state` and the verdict but MUST NOT decide the review event or thread handling, which fall back to the defaults with `policy_source: default`.

#### Scenario: Policy attempts approval through the legacy key

- **WHEN** a policy sets `publish_state: approve`
- **THEN** policy validation fails because the legacy key expresses only whether to publish

#### Scenario: Policy opts into approval

- **WHEN** a policy sets `publish.on_pass: approve` together with `publish.approve_requires_explicit_opt_in: false`
- **THEN** validation succeeds and PASS publishes an APPROVE review

#### Scenario: Policy attempts approval without the opt-in

- **WHEN** a policy sets `publish.on_pass: approve` and omits the opt-in
- **THEN** `run` exits 2 with failure code `publish_policy_invalid` and detail `approve_not_opted_in` before any review dispatch

### Requirement: Approval is expressible only through the repository policy

Neither `review` nor `run`/`auto` SHALL emit an approving review unless the effective repository policy sets `publish.on_pass: approve` together with `approve_requires_explicit_opt_in: false` and the run's verdict is PASS without any clamp. `--allow-approve` MUST remain non-enabling, MUST print that the publish policy selects approval, and MUST NOT change the event. Documentation MUST state that a bot APPROVE never satisfies code-owner review, may count toward `required_approving_review_count`, and may satisfy `require_last_push_approval`, and that the consuming repository owns that risk.

#### Scenario: Caller passes allow-approve

- **WHEN** `rvw auto --allow-approve` is invoked under the default policy
- **THEN** the CLI prints that the flag has no effect and the published review remains a COMMENT

#### Scenario: Repository opts in twice

- **WHEN** the base policy sets `on_pass: approve` and `approve_requires_explicit_opt_in: false` and the run passes cleanly
- **THEN** the review event is APPROVE

### Requirement: CI composition preserves auto and publication semantics

Automated invocations of the container image and the App MUST call `rvw run` and consume its canonical process and summary artifacts. They MUST preserve the reserved exit categories, MUST leave the review event to the Python side and the repository `publish` policy, MUST NOT convert BLOCK or failed execution to success, and MUST NOT use stdout prose to determine the result.

#### Scenario: CI auto finds policy blockers

- **WHEN** containerized evaluation returns BLOCK and publishes finding narratives under the default policy
- **THEN** the invoking automation reports failure from exit 1 and the published review is a COMMENT

#### Scenario: Consuming repository escalates

- **WHEN** the repository policy sets `publish.on_block: request_changes` and the App review returns BLOCK
- **THEN** the review is REQUEST_CHANGES while the check run conclusion stays `failure`

### Requirement: Run is the shared policy-gated execution entry

`rvw run` MUST accept `--target <pr-url|pr-number|sha>`, optional `--base-ref` and `--head-ref`, optional `--repo-dir`, `--out`, `--policy auto|PATH`, `--publish none|github-review`, and `--json`. It MUST accept `--publish github-comment` as a deprecated alias of `github-review` for one release, MUST print a deprecation warning, and MUST record the canonical value in the process contract and command. It MUST expose positive discovery and adjudication replica controls with defaults 1 and 3, positive concurrency default 8, per-execution deadline default 600 seconds restricted to 1 through 1800, and discovery mode `agentic|inline` defaulting to `agentic`. It MUST execute the existing shared pipeline once, evaluate policy only after checking execution status, and record effective settings. `--out DIR` MUST name the artifact directory itself, with no appended run ID; without it the ordinary `/tmp/rvw/<run-id>` root MUST remain available. The run ID MUST remain recorded independently of the output path.

#### Scenario: Caller chooses an artifact directory

- **WHEN** `rvw run --out /workspace/result` completes
- **THEN** the process, summary, stage files, and runtime evidence are written beneath `/workspace/result` and its process contract still records the run ID

#### Scenario: Host caller supplies no checkout

- **WHEN** an agentic `run` invocation omits `--repo-dir`
- **THEN** existing provisioning supplies a verified checkout for shared discovery and adjudication

#### Scenario: Caller uses the deprecated publish mode

- **WHEN** `rvw run --publish github-comment` is invoked
- **THEN** the command warns that the alias is deprecated and records `runtime.publish: github-review`
