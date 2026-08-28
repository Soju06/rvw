## MODIFIED Requirements

### Requirement: Runtime artifacts are persisted per replica

The Codex adapter MUST write `prompt.md`, `schema.json`, `out.json`, and `run.log` beneath an `r<replica>` artifact directory before or during execution and MUST derive the replica number from that directory name. Discovery and sampling MUST preserve the existing lane-or-variant `r<replica>` path for a one-chunk plan and MUST insert a `c<chunk>` directory immediately before `r<replica>` for a multi-chunk plan.

#### Scenario: Malformed run directory

- **WHEN** the adapter is given a directory not ending in `r<positive-integer>`
- **THEN** execution fails before assigning an ambiguous replica number

#### Scenario: One chunk preserves artifact paths

- **WHEN** a lane's diff fits in one chunk
- **THEN** its artifacts remain beneath `<lane>/r<replica>/` with no chunk directory

#### Scenario: Multiple chunks separate artifacts

- **WHEN** a lane's diff requires two chunks
- **THEN** its artifacts are separated beneath `<lane>/c1/r<replica>/` and `<lane>/c2/r<replica>/`
