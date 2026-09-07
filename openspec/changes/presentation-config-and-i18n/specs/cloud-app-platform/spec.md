## ADDED Requirements

### Requirement: App checks bootstrap presentation from the base revision

Before creating a check or sandbox, the App MUST read `.rvw/config.yaml` through the repository contents API with the captured base SHA and installation token. Missing config MUST select rvw/en defaults. Malformed config MUST select those bootstrap defaults and record `presentation_config_invalid` for the final check. Final Python-resolved presentation MUST supersede bootstrap presentation; check updates MUST support updating `name` to `short_name`. Check `external_id` MUST remain the job ID.

#### Scenario: PR changes display name

- **WHEN** base and head configuration differ
- **THEN** bootstrap check uses the base display name and short_name

#### Scenario: Malformed bootstrap configuration

- **WHEN** the contents response is malformed or schema-invalid
- **THEN** the initial check uses rvw/en and the final check reports presentation_config_invalid

### Requirement: App check chrome is localized and separates diagnostics

Worker Korean and English catalogs MUST have identical keys and format-compatible messages covering bootstrap, completion, deadline, superseded, exhausted queue, and missing-artifact paths. The check name MUST equal `short_name`; title MUST combine `display_name` with localized in-progress, complete, needs-changes, or incomplete state. A completed summary MUST state completion and blocker plus warning/suggestion counts with partial-coverage disclosure when applicable. Neutral or failure summaries MUST use a localized human-reason sentence without job IDs, stderr dumps, or operational counters. Structured job ID, counts, lane validity, and artifact key MUST be retained in the check `text` collapsed section and artifacts. Python summary presentation MUST govern final check chrome.

#### Scenario: Completed check

- **WHEN** Python supplies locale ko with configured display and short names
- **THEN** the check uses those names and a Korean completion summary while structured details remain in text

#### Scenario: Deadline expires

- **WHEN** a job exceeds its deadline before Python completes
- **THEN** the check uses catalog-localized incomplete prose and preserves job and diagnostic details in text
