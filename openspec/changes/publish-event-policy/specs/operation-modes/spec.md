## MODIFIED Requirements

### Requirement: Auto policy is strict YAML

An auto policy MUST strictly define `promote_to_blocker`, `drop`, `block_when`, and `publish_state`. It MUST accept optional boolean `allow_language_fallback` defaulting to false. The `publish_state` field MUST accept only `comment` or `none` and MUST keep deciding whether the policy-gated commands publish at all. The policy MUST accept an optional strict `publish` block (`on_block`: `comment` or `request_changes`; `on_pass`: `comment`, `approve`, or `none`; boolean `dismiss_on_pass`; boolean `approve_requires_explicit_opt_in` defaulting to true) and an optional strict `threads` block (boolean `resolve_on_fix` and `reuse_open_thread`, both defaulting to true). A fault inside either block MUST be reported as `publish_policy_invalid` (exit 2, status `invalid`) with `approve_not_opted_in` as the detail when `on_pass: approve` lacks `approve_requires_explicit_opt_in: false`; faults elsewhere in the policy MUST keep the existing `invalid_policy` classification.

#### Scenario: Policy attempts approval through the legacy key

- **WHEN** a policy sets `publish_state: approve`
- **THEN** policy validation fails because the legacy key expresses only whether to publish

#### Scenario: Policy opts into approval

- **WHEN** a policy sets `publish.on_pass: approve` together with `publish.approve_requires_explicit_opt_in: false`
- **THEN** validation succeeds and PASS publishes an APPROVE review

#### Scenario: Policy attempts approval without the opt-in

- **WHEN** a policy sets `publish.on_pass: approve` and omits the opt-in
- **THEN** `run` exits 2 with failure code `publish_policy_invalid` and detail `approve_not_opted_in` before any review dispatch
