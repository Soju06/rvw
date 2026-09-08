## ADDED Requirements

### Requirement: Publication and thread policy are anchored and strict

The repository auto policy at `.rvw/policies/auto.yaml` MUST accept an optional `publish` block with `on_block` (`comment` or `request_changes`, default `comment`), `on_pass` (`comment`, `approve`, or `none`, default `comment`), boolean `dismiss_on_pass` (default false), and boolean `approve_requires_explicit_opt_in` (default true), and an optional `threads` block with boolean `resolve_on_fix` (default true) and boolean `reuse_open_thread` (default true). Both blocks MUST be read through the same base-revision reader boundary as repository lanes, presentation, and the rest of the auto policy, and MUST NOT be read from the pull-request head or the working tree unless explicit `--allow-worktree-rules` applies. Unknown keys, unknown values, and non-strict scalar types in either block MUST fail closed with machine-readable reason `publish_policy_invalid` before review dispatch, and `on_pass: approve` without `approve_requires_explicit_opt_in: false` in the same file MUST fail with detail `approve_not_opted_in`. A missing policy file or a policy without these blocks MUST resolve to the defaults, which reproduce COMMENT-only publication.

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
