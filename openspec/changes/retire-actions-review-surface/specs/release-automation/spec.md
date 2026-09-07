## MODIFIED Requirements

### Requirement: Container consumers pin a versioned image reference

Container guidance MUST NOT present a floating default image reference for review runs.
Operator guidance MUST show a release-version tag pin for explicit upgrades and an
immutable digest pin derived from release output, and MUST identify `latest` as a mutable
convenience tag that is not a reproducible reference.

#### Scenario: Operator runs the published image

- **WHEN** an operator follows the container guidance to run the image directly
- **THEN** the documented command supplies an explicit release-version image tag or its published digest rather than the mutable `latest` tag
