## ADDED Requirements

### Requirement: Reusable deployment runner is caller-selectable

The reusable deployment workflow MUST expose an optional `runs_on` input of type
`string`, defaulting to `ubuntu-latest`. Every job in that workflow MUST use the
input directly as a single runner label without JSON decoding. The input MUST
support only a single label string; label arrays and runner groups are unsupported.

#### Scenario: Caller omits the runner input

- **WHEN** a caller invokes the reusable deployment workflow without `runs_on`
- **THEN** the deploy job uses `ubuntu-latest`

#### Scenario: Caller selects a runner label

- **WHEN** a caller supplies `runs_on: blacksmith-2vcpu-ubuntu-2404`
- **THEN** the deploy job uses the literal label `blacksmith-2vcpu-ubuntu-2404`
  without interpreting it as JSON
