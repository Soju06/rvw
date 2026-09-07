## ADDED Requirements

### Requirement: Execution contracts retain presentation and language publication outcomes

The shared process and summary contracts MUST expose the resolved strict presentation configuration and publication failure/fallback facts so adapters and replay consume the same snapshot. Missing presentation in a legacy retained run MUST resolve to the documented rvw/en defaults. Invalid configured presentation MUST produce `presentation_config_invalid` with invalid status and exit 2 before runtime dispatch. Persistent publication language mismatch MUST produce `publication_language_mismatch` with infrastructure-failure status and exit 3 while retaining review evidence and localized counts; fallback use MUST be recorded as `language_fallback_used: true`. A rewrite MUST use the existing bounded read-only runtime abstraction with an injectable prose-only rewriting interface and strict segment-count validation.

#### Scenario: Invalid presentation before discovery

- **WHEN** target anchoring succeeds but presentation validation fails
- **THEN** process and summary retain presentation_config_invalid and no model runs

#### Scenario: Language rewrite fails

- **WHEN** publication still mismatches after one bounded rewrite
- **THEN** the process reports infrastructure failure and exit 3 with publication_language_mismatch while retained adjudication evidence is unchanged
