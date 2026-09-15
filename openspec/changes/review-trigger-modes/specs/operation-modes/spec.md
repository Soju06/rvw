## ADDED Requirements

### Requirement: Selectable event controls extend strict trigger policy

The existing strict `triggers` object MUST additionally accept boolean `dedupe_same_head` (default true) and strict `events` with `pull_request.enabled` (default true), `pull_request.actions` (default `[opened, synchronize, reopened, ready_for_review]`), `mention.enabled` (default true), `mention.surfaces` (default `[issue_comment, pull_request_review_comment]`), and `mention.allow` (default `[OWNER, MEMBER, COLLABORATOR]`). Actions MUST be restricted to `opened`, `synchronize`, `reopened`, and `ready_for_review`; surfaces to `issue_comment` and `pull_request_review_comment`; associations to `OWNER`, `MEMBER`, `COLLABORATOR`, `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, `FIRST_TIMER`, `NONE`, and `MANNEQUIN`. Empty event-selection lists MUST be valid and select nothing. `mode: allowlist` with empty `rules` MUST remain invalid; empty `mention.allow` MUST remain valid. Existing rule matching, default non-draft eligibility, and policy size bounds MUST remain unchanged, with additional App event selection and PR-scoped completed-head dedupe applied to eligible automatic events. Nested keys and booleans MUST be strict, rejecting unknown keys/values and quoted, numeric, or single-letter booleans through the existing machine-readable policy-invalid contract.

Automatic same-head dedupe MUST scope check evidence to the requested installation, repository, PR, and head through recoverable job identity. A parseable check external ID or structured job/artifact identity identifying another job MUST reject that check even when its pull_requests associations include the requested PR. Commit association alone MUST NOT suppress admission.

Every valid shared parser fixture in the policies, auto_policies, and raw yaml_policies categories MUST contain an exact normalized expected output asserted by both Python and Worker. Shared rule matching and evaluation fixtures MUST retain equal results. Packaged defaults MUST use exactly the four existing automatic actions and MUST NOT name bot logins. CLI review commands MUST retain their existing rule/draft and force behavior without a comment entry point.

#### Scenario: Mention-only and cheaper-auto policies validate

- **WHEN** a repository disables pull_request events or selects only opened and ready_for_review actions
- **THEN** Python and Worker accept the same document and preserve enabled mention defaults

#### Scenario: Empty mention selection is distinct from empty rule allowlist

- **WHEN** policy validation receives `mode: allowlist` with empty `rules`, or an empty mention allow list in a valid denylist policy
- **THEN** it rejects the former and accepts the latter with no authorized mention associations

#### Scenario: Nested trigger validation is strict

- **WHEN** a new trigger block contains an unknown key, enum value, quoted boolean, numeric boolean, or single-letter boolean
- **THEN** both readers reject it through their existing machine-readable policy-invalid contract

#### Scenario: All valid parser fixtures have exact expected facts

- **WHEN** either runtime runs the shared parser fixtures
- **THEN** it compares every accepted document's full normalized output with the shared expected value

#### Scenario: Check association contradicts review ownership

- **WHEN** an automatic event finds a completed check whose job identity belongs to another PR while pull_requests lists the requested PR
- **THEN** same-head dedupe does not suppress the requested PR

### Requirement: Policy lint warns about an empty automatic action selection

`rvw policy lint [PATH] [--json]` MUST validate the selected auto policy with the existing strict parser and default PATH to `.rvw/policies/auto.yaml`. A valid policy with `triggers.events.pull_request.enabled: true` and `actions: []` MUST emit warning code `empty-pull-request-actions` and exit zero. Disabled automatic events with empty actions MUST NOT emit that warning. JSON output MUST preserve the warning's machine-readable code. Missing or invalid policy MUST exit 2 with the existing machine-readable validation reason.

#### Scenario: Automatic events are enabled with no actions

- **WHEN** policy lint reads enabled pull_request events with an empty actions list
- **THEN** it warns that no automatic reviews are selected while validation succeeds with exit zero

#### Scenario: Automatic events are deliberately disabled

- **WHEN** policy lint reads disabled pull_request events with an empty actions list
- **THEN** it emits no empty-action warning and exits zero

#### Scenario: Policy lint receives invalid input

- **WHEN** the selected policy is missing or malformed
- **THEN** lint exits 2 with the existing machine-readable validation reason

## MODIFIED Requirements

### Requirement: Trigger outcomes are preserved as facts

`summary.json` MUST accept strict `trigger` facts with boolean `skipped`, nullable string `rule`, `mode` (`denylist` or `allowlist`), nullable `bypassed` (`force` or `rerequested`), nullable string `policy_error`, and boolean `not_applicable`. Legacy summaries lacking `trigger` MUST remain readable. The App summary parser MUST accept these facts and the final check facts MUST preserve them, including a webhook bypass or policy-read diagnostic when the review fails before Python finishes. Worker-supplied trigger facts MUST be bound to the reviewed base and head; a stale snapshot MUST fail the target-anchor check.

The top-level `summary.trigger.skipped` field MUST additionally accept only the string reasons `events_disabled`, `action_not_selected`, `same_head_reviewed`, and `in_flight_same_head`. Trigger facts MUST also accept `source` (`pull_request` or `mention`, default `pull_request`), nullable string `actor` (default null), and nullable positive integer `comment_id` (default null). Both readers MUST supply these defaults for legacy summaries lacking the fields or the entire trigger object. Mention provenance MUST remain in top-level summary trigger and final check facts, without a competing trigger object in publish.

#### Scenario: Human rerequest finishes

- **WHEN** an App review is started by `check_run.rerequested`
- **THEN** both the Python summary and final check retain `trigger.bypassed: rerequested`

#### Scenario: Legacy summary supplies trigger defaults

- **WHEN** Python or the App reads a summary without trigger facts
- **THEN** source defaults to pull_request, actor and comment_id to null, and skipped to false

#### Scenario: Mention facts survive execution

- **WHEN** a human mention initiates a run
- **THEN** summary and final check retain source mention, the commenter login, and comment id bound to the reviewed anchors
