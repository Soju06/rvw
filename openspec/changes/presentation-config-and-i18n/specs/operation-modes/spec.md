## ADDED Requirements

### Requirement: Language fallback is explicit and recorded

Publication-capable CLI commands MUST accept `--allow-language-fallback`; strict auto policy MUST accept boolean `allow_language_fallback` defaulting to false. Explicit CLI opt-in or a true resolved auto policy MUST permit mismatched publication prose only with `language_fallback_used: true` in the outcome/summary. Without opt-in, persistent `publication_language_mismatch` MUST suppress prose and exit 3, distinct from PASS 0 and BLOCK 1. An App check MUST still complete using a catalog-localized outcome sentence.

#### Scenario: Default locale failure

- **WHEN** the one bounded rewrite fails the publication language gate with fallback disabled
- **THEN** no review prose is sent, publication_language_mismatch is recorded, and exit is 3

#### Scenario: Auto fallback policy

- **WHEN** resolved auto policy enables allow_language_fallback
- **THEN** auto passes the opt-in to publication and records use only when mismatch is bypassed
