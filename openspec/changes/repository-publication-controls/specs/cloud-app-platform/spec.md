## MODIFIED Requirements

### Requirement: App Check conclusions follow canonical execution status

The App MUST map a valid `pass` process contract with exit 0 and positive VALID coverage to Check conclusion `success` by default, `block` with exit 1 to `failure` by default, and `invalid` or `infra_failed` to `neutral`. Missing, malformed, inconsistent, or unsupported process or summary contracts MUST result in `neutral`. Zero VALID lanes MUST always produce `neutral`, including an otherwise valid-shaped PASS envelope. Check summary facts and common text MUST come from Python's summary; adapter-specific titles, links, and operational detail MUST remain separate presentation duties.

Base-policy `publish.checks.on_pass` MUST accept success or neutral (default success); `on_block` MUST accept failure or neutral (default failure). Invalid, infrastructure and deadline outcomes MUST remain neutral. Base-policy `publish.channels` MUST govern App publication: absent review MUST prevent review/comment/thread writes and omit `--publish`; checks-only completion MUST retain the human summary. Absent checks MUST suppress detailed check updates after bootstrap and MUST terminalize the mandatory check as neutral with localized publication-without-check-details text.

#### Scenario: Empty coverage is presented as PASS

- **WHEN** the process envelope says `pass` but summary records zero VALID lanes
- **THEN** the Check conclusion is `neutral` and never `success`

#### Scenario: Policy blocks after valid execution

- **WHEN** process status is `block`, exit code is 1, and the summary records valid execution
- **THEN** the Check concludes `failure` using the shared summary facts

#### Scenario: Checks-only legacy policy

- **WHEN** the captured base policy uses publish_state none without explicit channels
- **THEN** the App omits --publish, creates no review or threads and retains the human check summary

#### Scenario: Review-only publication

- **WHEN** captured base channels contain only review
- **THEN** the bootstrap check receives a terminal neutral state without detailed review facts

#### Scenario: Advisory BLOCK

- **WHEN** valid execution blocks and captured base publish.checks.on_block is neutral
- **THEN** the check concludes neutral without changing the BLOCK review judgment

### Requirement: App accepts repository voice and synthesis facts

The Worker MUST parse the same optional voice audience, register, guidance, examples and allowed_terms fields and defaults as Python, including multiline YAML guidance and the 800-character cap. Unknown or invalid voice settings MUST follow the existing presentation_config_invalid bootstrap failure path. The Worker MUST accept summary contracts with or without synthesis, validate present synthesis facts, and include synthesis status and supplied telemetry in the check text JSON facts without changing check conclusion policy.

Worker and Python MUST agree on strict `voice.examples` (at most three strings, at most 200 Unicode characters each), `voice.allowed_terms` (strings) and `synthesis.enabled` (boolean, default true). Shared fixtures MUST cover acceptance, defaults and rejection. Summary contracts MUST accept synthesis status disabled and publish channels plus `inline_policy` with severity_at_least, max_comments and body_only_count, defaulting legacy contracts safely. Check facts MUST retain the fields when checks are enabled.

#### Scenario: Multiline repository guidance

- **WHEN** a base configuration supplies voice mixed/neutral and valid multiline guidance
- **THEN** Python and Worker retain identical voice values

#### Scenario: Synthesis fallback in a completed review

- **WHEN** Python summary reports fallback:schema-invalid and the review otherwise passes
- **THEN** the check facts expose the fallback status and the check conclusion remains governed by existing review policy
