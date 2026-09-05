## ADDED Requirements

### Requirement: Auto policy resolution is portable and precedence-ordered

Policy-gated `run` and `auto` MUST resolve policy in this order: an explicit policy path; `.rvw/policies/auto.yaml` read from the captured base commit; an existing external `~/.hermes/review/policies/auto.yaml`; and the packaged `rvw/resources/policies/auto-default.yaml`. Selecting the external policy MUST emit a deprecation warning. The packaged default MUST be installed with the Python distribution and available equally to host, Actions, and App. An explicit missing path or malformed selected policy MUST be an invalid configuration and MUST NOT silently fall through to a lower-priority source. The effective source and path MUST be recorded in `process.json`; package fallback MUST NOT require modifying the external registry.

#### Scenario: Base policy and external policy coexist

- **WHEN** the captured base commit contains a policy and no explicit path is supplied
- **THEN** that base policy wins and the process envelope identifies source `repository`

#### Scenario: Fresh host has no policy registry

- **WHEN** no explicit, base-commit, or external policy exists
- **THEN** policy resolution uses the packaged default and records source `package`

#### Scenario: External compatibility policy is used

- **WHEN** only the external policy exists
- **THEN** it wins over the package default, emits a deprecation warning, and records source `external`

#### Scenario: Explicit policy wins

- **WHEN** an explicit valid policy path is supplied alongside repository and external policies
- **THEN** the explicit policy is used and source is `explicit`

#### Scenario: Base policy is malformed

- **WHEN** the captured base commit contains an invalid auto policy
- **THEN** the command exits 2 with a policy configuration failure rather than using another source
