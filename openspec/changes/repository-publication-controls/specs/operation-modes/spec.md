## MODIFIED Requirements

### Requirement: Auto policy is strict YAML

An auto policy MUST strictly define `promote_to_blocker`, `drop`, `block_when`, and `publish_state`. It MUST accept optional boolean `allow_language_fallback` defaulting to false. The `publish_state` field MUST accept only `comment` or `none` and MUST map to channels `[checks]` when none and explicit channels are absent. The policy MUST accept an optional strict `publish` block (`on_block`: `comment` or `request_changes`; `on_pass`: `comment`, `approve`, or `none`; boolean `dismiss_on_pass`; boolean `approve_requires_explicit_opt_in` defaulting to true) and an optional strict `threads` block (boolean `resolve_on_fix` and `reuse_open_thread`, both defaulting to true). A fault inside either block MUST be reported as `publish_policy_invalid` (exit 2, status `invalid`) with `approve_not_opted_in` as the detail when `on_pass: approve` lacks `approve_requires_explicit_opt_in: false`; faults elsewhere in the policy MUST keep the existing `invalid_policy` classification, at publication sites as well. The deprecated external policy file MAY still decide `publish_state` and the verdict but MUST NOT decide the review event or thread handling, which fall back to the defaults with `policy_source: default`.

The strict publish block MUST additionally accept channels (a nonempty list drawn from checks and review; default both), checks (on_block failure|neutral and on_pass success|neutral with failure/success defaults), and inline (severity_at_least suggestion|warning|blocker default suggestion; max_comments nonnegative integer|null default null). Explicit channels MUST take precedence over the legacy publish_state mapping. Python and Worker readers MUST fail closed on invalid values with publish_policy_invalid.

#### Scenario: Policy attempts approval through the legacy key

- **WHEN** a policy sets `publish_state: approve`
- **THEN** policy validation fails because the legacy key expresses only whether to publish

#### Scenario: Policy opts into approval

- **WHEN** a policy sets `publish.on_pass: approve` together with `publish.approve_requires_explicit_opt_in: false`
- **THEN** validation succeeds and PASS publishes an APPROVE review

#### Scenario: Policy attempts approval without the opt-in

- **WHEN** a policy sets `publish.on_pass: approve` and omits the opt-in
- **THEN** `run` exits 2 with failure code `publish_policy_invalid` and detail `approve_not_opted_in` before any review dispatch

#### Scenario: Empty publication channels

- **WHEN** publish.channels is an empty list
- **THEN** Python and Worker reject publication policy with publish_policy_invalid

## ADDED Requirements

### Requirement: Operator summaries follow presentation locale

Operator-facing plan, result and thread summaries and gate errors MUST use the resolved presentation locale through matching English and Korean catalogs. Machine-readable reasons, exit codes and JSON keys MUST remain unchanged.

#### Scenario: Korean operator output

- **WHEN** presentation resolves to ko and the CLI renders a plan, result, thread summary or gate error
- **THEN** human prose uses Korean and machine reason identifiers remain English
