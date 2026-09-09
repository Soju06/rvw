## ADDED Requirements

### Requirement: App accepts repository voice and synthesis facts

The Worker MUST parse the same optional voice audience, register and guidance fields and defaults as Python, including multiline YAML guidance and the 800-character cap. Unknown or invalid voice settings MUST follow the existing presentation_config_invalid bootstrap failure path. The Worker MUST accept summary contracts with or without synthesis, validate present synthesis facts, and include synthesis status and supplied telemetry in the check text JSON facts without changing check conclusion policy.

#### Scenario: Multiline repository guidance

- **WHEN** a base configuration supplies voice mixed/neutral and valid multiline guidance
- **THEN** Python and Worker retain identical voice values

#### Scenario: Synthesis fallback in a completed review

- **WHEN** Python summary reports fallback:schema-invalid and the review otherwise passes
- **THEN** the check facts expose the fallback status and the check conclusion remains governed by existing review policy
