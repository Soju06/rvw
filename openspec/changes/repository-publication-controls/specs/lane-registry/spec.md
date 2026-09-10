## MODIFIED Requirements

### Requirement: Presentation configuration is anchored and strict

Repository `.rvw/config.yaml` MUST be resolved once after target anchoring through the same base-revision reader boundary as repository lanes and auto policy. It MUST NOT read PR-head or working-tree content unless explicit `--allow-worktree-rules` applies; that override MUST emit the same non-SoT warning as repository rules. Configuration MUST accept only `display_name` (nonblank single-line string at most 80 characters), `short_name` (nonblank single-line string at most 40 characters), `locale` (`ko` or `en`), nullable plain-text `footer` (at most 240 characters), and optional strict `voice` with audience `engineers|mixed` (default engineers), register `formal|neutral` (default formal), optional string guidance of at most 800 Unicode characters, examples (at most three strings each at most 200 Unicode characters, default empty), and allowed_terms (strings, default empty). Unknown fields, wrong types, and control characters MUST be rejected. Missing configuration MUST resolve to `display_name: rvw`, `short_name: rvw`, `locale: en`, `footer: null`, and voice defaults engineers/formal with absent guidance; malformed configuration MUST prevent review execution with machine-readable reason `presentation_config_invalid`. The resolved object MUST be persisted as `presentation.json` and report/publication replay MUST use that snapshot instead of re-reading repository configuration.

Configuration MUST additionally accept strict synthesis with boolean enabled default true. These settings MUST share the existing base-revision trust boundary and persisted snapshot.

#### Scenario: PR changes its own presentation

- **WHEN** the PR head changes locale or branding while the captured base has another configuration
- **THEN** review uses the captured base configuration

#### Scenario: Missing configuration

- **WHEN** the base contains no presentation file
- **THEN** review uses the documented defaults

#### Scenario: Malformed configuration

- **WHEN** the base configuration has an unknown field or invalid name
- **THEN** review does not dispatch and records presentation_config_invalid

#### Scenario: Replay after configuration changes

- **WHEN** a saved run is reported or published after repository configuration changes
- **THEN** the saved presentation snapshot determines branding and locale

#### Scenario: Explicit working-tree override

- **WHEN** an operator opts into worktree rules
- **THEN** presentation uses that same opt-in and emits the non-SoT warning

#### Scenario: Invalid synthesis or example setting

- **WHEN** synthesis.enabled is a string or voice.examples has four items or an item longer than 200 Unicode characters
- **THEN** Python and Worker reject the configuration with presentation_config_invalid

### Requirement: Publication and thread policy are anchored and strict

The repository auto policy at `.rvw/policies/auto.yaml` MUST accept an optional `publish` block with `on_block` (`comment` or `request_changes`, default `comment`), `on_pass` (`comment`, `approve`, or `none`, default `comment`), boolean `dismiss_on_pass` (default false), boolean `approve_requires_explicit_opt_in` (default true), nonempty channels (checks|review, default both unless legacy publish_state none maps to checks), checks (on_block failure|neutral default failure; on_pass success|neutral default success), and inline (severity_at_least suggestion|warning|blocker default suggestion; max_comments nonnegative integer|null default null), and an optional `threads` block with boolean `resolve_on_fix` (default true) and boolean `reuse_open_thread` (default true). Both blocks MUST be read through the same base-revision reader boundary as repository lanes, presentation, and the rest of the auto policy, and MUST NOT be read from the pull-request head or the working tree unless explicit `--allow-worktree-rules` applies. Unknown keys, unknown values, and non-strict scalar types in either block MUST fail closed with machine-readable reason `publish_policy_invalid` before review dispatch, and `on_pass: approve` without `approve_requires_explicit_opt_in: false` in the same file MUST fail with detail `approve_not_opted_in`. A missing policy file or a policy without these blocks MUST resolve to the defaults, which reproduce COMMENT-only publication.

#### Scenario: Base policy escalates while the head weakens it

- **WHEN** the captured base sets `publish.on_block: request_changes` and the pull-request head changes the same file to `on_pass: approve`
- **THEN** review uses the base block, publishes REQUEST_CHANGES on BLOCK, and never reads the head value

#### Scenario: Policy without the new blocks

- **WHEN** the base policy declares only the historical promote, drop, block, and `publish_state` keys
- **THEN** the effective `publish` and `threads` blocks are the documented defaults

#### Scenario: Approve without the opt-in

- **WHEN** the base policy sets `publish.on_pass: approve` and leaves `approve_requires_explicit_opt_in` at its default
- **THEN** the run records `publish_policy_invalid` with detail `approve_not_opted_in`, exits 2, and dispatches no review

#### Scenario: Unknown event value

- **WHEN** the base policy sets `publish.on_block: approve` or `threads.resolve_on_fix: "yes"`
- **THEN** the run records `publish_policy_invalid` naming the offending key and does not publish
