## ADDED Requirements

### Requirement: Language fallback is explicit and recorded

Publication-capable CLI commands MUST accept `--allow-language-fallback`; strict auto policy MUST accept boolean `allow_language_fallback` defaulting to false. Explicit CLI opt-in or a true resolved auto policy MUST permit mismatched publication prose only with `language_fallback_used: true` in the outcome/summary. Without opt-in, persistent `publication_language_mismatch` MUST suppress prose and exit 3, distinct from PASS 0 and BLOCK 1. An App check MUST still complete using a catalog-localized outcome sentence.

#### Scenario: Default locale failure

- **WHEN** the one bounded rewrite fails the publication language gate with fallback disabled
- **THEN** no review prose is sent, publication_language_mismatch is recorded, and exit is 3

#### Scenario: Auto fallback policy

- **WHEN** resolved auto policy enables allow_language_fallback
- **THEN** auto passes the opt-in to publication and records use only when mismatch is bypassed

## MODIFIED Requirements

### Requirement: Auto policy is strict YAML

An auto policy MUST strictly define `promote_to_blocker`, `drop`, `block_when`, and `publish_state`. It MUST accept optional boolean `allow_language_fallback` defaulting to false. The `publish_state` field MUST accept only `comment` or `none`.

#### Scenario: Policy attempts approval

- **WHEN** a policy sets `publish_state: approve`
- **THEN** policy validation fails because approval is not expressible

### Requirement: Auto exposes a CI exit contract

The `run` and `auto` commands MUST reserve exit 0 for policy PASS, 1 for policy BLOCK, 2 for invalid input or configuration, and 3 for infrastructure failure. Invalid targets, anchor mismatches, absent explicitly selected policies, invalid policy content, and invalid presentation configuration MUST exit 2. Checkout, runtime, adjudication, publication, and unexpected execution exceptions MUST exit 3 and MUST NOT escape as exit 1. A failed review summary or zero VALID discovery coverage MUST exit 3 with a machine-readable `review_failed:<detail>` reason even when merge and adjudication are empty. A publication that still fails the locale gate after one bounded rewrite MUST exit 3 with status `infra_failed` and reason `publication_language_mismatch`, unless explicit language fallback is enabled.

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
