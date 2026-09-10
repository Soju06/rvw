## MODIFIED Requirements

### Requirement: Presentation configuration is anchored and strict

Repository `.rvw/config.yaml` MUST be resolved once after target anchoring through the same base-revision reader boundary as repository lanes and auto policy. It MUST NOT read PR-head or working-tree content unless explicit `--allow-worktree-rules` applies; that override MUST emit the same non-SoT warning as repository rules. Configuration MUST accept only `display_name` (nonblank single-line string at most 80 characters), `short_name` (nonblank single-line string at most 40 characters), `locale` (`ko` or `en`), nullable plain-text `footer` (at most 240 characters), and optional strict `voice` with audience `engineers|mixed` (default engineers), register `formal|neutral` (default formal), and optional string guidance of at most 800 Unicode characters. Unknown fields, wrong types, and control characters MUST be rejected. Missing configuration MUST resolve to `display_name: rvw`, `short_name: rvw`, `locale: en`, `footer: null`, and voice defaults engineers/formal with absent guidance; malformed configuration MUST prevent review execution with machine-readable reason `presentation_config_invalid`. The resolved object MUST be persisted as `presentation.json` and report/publication replay MUST use that snapshot instead of re-reading repository configuration.

#### Scenario: PR changes its own presentation

- **WHEN** the PR head changes locale or branding while the captured base has another configuration
- **THEN** review uses the captured base configuration

#### Scenario: Missing configuration

- **WHEN** the base contains no presentation file
- **THEN** review uses the documented defaults

#### Scenario: Malformed configuration

- **WHEN** the base configuration has an unknown field or invalid name
- **THEN** review does not dispatch and records presentation_config_invalid

#### Scenario: Replay after configuration changes

- **WHEN** a saved run is reported or published after repository configuration changes
- **THEN** the saved presentation snapshot determines branding and locale

#### Scenario: Explicit working-tree override

- **WHEN** an operator opts into worktree rules
- **THEN** presentation uses that same opt-in and emits the non-SoT warning
