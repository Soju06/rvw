## ADDED Requirements

### Requirement: Pull request review eligibility is repository policy

The auto policy MUST accept optional strict `triggers` with `mode` (`denylist` or `allowlist`, default `denylist`), `drafts` (`skip` or `review`, default `skip`), and `rules` (default empty). Each rule MUST have a unique name matching `[a-z0-9-]+` and at least one matching field: `authors`, `head_branches`, `base_branches`, and `labels` as string lists, or `title` as a portable regular expression. Authors and labels MUST match exact names case-insensitively, retaining bot login suffixes. Branch patterns MUST use case-sensitive fnmatch semantics against ref names, including slash-spanning wildcards. Title patterns MUST use search semantics and reject invalid syntax, lookbehind, named groups, and constructs whose meaning differs between Python and JavaScript. Unknown keys, values, and non-strict trigger scalar types MUST fail closed with the existing policy-invalid reason. Python and Worker parsers and matchers MUST agree on shared offline fixtures.

Rule fields MUST be ANDed; values in a list and separate rules MUST be ORed. A denylist MUST skip on the first matching rule; an allowlist MUST skip when no rule matches and MUST reject an empty rules list. Missing `triggers` MUST preserve every non-draft PR's eligibility. Packaged defaults MUST NOT name bot logins.

#### Scenario: Changesets release metadata matches

- **WHEN** a PR authored by `github-actions[bot]` has head ref `changeset-release/main` and the repository rule requires that author and `changeset-release/*`
- **THEN** it matches regardless of its diff, while an unrelated author rule does not match

#### Scenario: A malformed filter cannot silently skip all reviews

- **WHEN** the selected policy has an empty allowlist, an empty rule, an unknown trigger field, a duplicate rule name, or an invalid title regex
- **THEN** policy validation fails with a machine-readable policy-invalid reason

### Requirement: CLI review commands honor repository triggers

For a PR target, `rvw run`, `rvw auto`, and `rvw review` MUST evaluate the resolved base-ref policy before discovery, using only author login, head/base ref names, labels, title, and draft metadata. A skipped PR MUST exit zero, print one localized line through the resolved presentation locale in human-readable mode (`review skipped by repository policy: <rule>` in English), write a minimal `summary.json` carrying trigger facts, and perform no discovery or publication. `rvw run --json` and `rvw auto --json` MUST preserve the existing machine-readable process contract. An allowlist miss MUST record a null rule with an explicit no-matching-rule human reason; a draft skip MUST record a null rule with a draft human reason. All three commands MUST expose `--force-review`, which bypasses matching and records `trigger.bypassed: force`. SHA and uncommitted targets MUST bypass matching and record `trigger.not_applicable: true`. Trigger policy MUST NOT be sourced from the deprecated external registry.

#### Scenario: Force review

- **WHEN** a PR matching a denylist rule is reviewed with `--force-review`
- **THEN** the review proceeds and facts record `trigger.bypassed: force`

#### Scenario: Skipped PR

- **WHEN** a PR matches a denylist rule named `changesets-release`
- **THEN** the command exits zero without discovery and writes `trigger.skipped: true` and `trigger.rule: changesets-release`

#### Scenario: Localized skip output

- **WHEN** a PR is skipped by a matching rule, an allowlist miss, or draft policy and presentation resolves to ko
- **THEN** the command and persisted summary use Korean skip prose while trigger facts keep their machine-readable values

#### Scenario: Skipped summary retains publication controls

- **WHEN** repository triggers skip a PR with explicit publication channels and inline settings
- **THEN** its summary retains the resolved publication settings alongside trigger facts with zero body-only findings and no publication

#### Scenario: Non-PR target

- **WHEN** the target is a SHA or uncommitted checkout
- **THEN** trigger matching is not applicable and facts record `trigger.not_applicable: true`

### Requirement: Trigger outcomes are preserved as facts

`summary.json` MUST accept strict `trigger` facts with boolean `skipped`, nullable string `rule`, `mode` (`denylist` or `allowlist`), nullable `bypassed` (`force` or `rerequested`), nullable string `policy_error`, and boolean `not_applicable`. Legacy summaries lacking `trigger` MUST remain readable. The App summary parser MUST accept these facts and the final check facts MUST preserve them, including a webhook bypass or policy-read diagnostic when the review fails before Python finishes. Worker-supplied trigger facts MUST be bound to the reviewed base and head; a stale snapshot MUST fail the target-anchor check.

#### Scenario: Human rerequest finishes

- **WHEN** an App review is started by `check_run.rerequested`
- **THEN** both the Python summary and final check retain `trigger.bypassed: rerequested`

## MODIFIED Requirements

### Requirement: Auto exposes a CI exit contract

The `run` and `auto` commands MUST reserve exit 0 for policy PASS or a recorded repository-trigger skip, 1 for policy BLOCK, 2 for invalid input or configuration, and 3 for infrastructure failure. Invalid targets, anchor mismatches, absent explicitly selected policies, invalid policy content, and invalid presentation configuration MUST exit 2. Checkout, runtime, adjudication, publication, and unexpected execution exceptions MUST exit 3 and MUST NOT escape as exit 1. For an executed review, a failed review summary or zero VALID discovery coverage MUST exit 3 with a machine-readable `review_failed:<detail>` reason even when merge and adjudication are empty. A publication that still fails the locale gate after one bounded rewrite MUST exit 3 with status `infra_failed` and reason `publication_language_mismatch`, unless explicit language fallback is enabled.

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
