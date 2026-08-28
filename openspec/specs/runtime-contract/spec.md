# runtime-contract

## Purpose

Define strict runtime schemas, validity classification, artifact seams, and the boundary between runtime wire output and enriched pipeline models.

## Requirements

### Requirement: Lane schemas close rule identifiers

Every lane runtime schema MUST restrict `rule_id` to the lane's declared rules plus one `<rule-namespace>/other` value derived from the first declared rule.

#### Scenario: Lane declares security rules

- **WHEN** a lane's first rule is `security/exposure`
- **THEN** its runtime schema allows declared rule IDs and `security/other` but no arbitrary string

### Requirement: Severity respects the lane cap

Every lane runtime schema MUST enumerate only severities at or below the lane's configured severity cap.

#### Scenario: Sweep is warning-capped

- **WHEN** a lane declares `severity_cap: warning`
- **THEN** its schema allows `warning` and `suggestion` and excludes `blocker`

### Requirement: Runtime output is strict JSON

Lane and adjudication runtime schemas MUST reject extra object properties and MUST list every property at every object level in `required` for OpenAI strict structured-output compatibility.

#### Scenario: Defaulted output property

- **WHEN** Pydantic would normally omit a defaulted property from JSON Schema `required`
- **THEN** schema generation adds that property to `required` before passing the schema to Codex

### Requirement: Runtime findings use the wire shape

A lane runtime output MUST contain a verdict string and a findings list whose items contain exactly `rule_id`, `file`, integer new-side `line`, `severity`, and `body`.

#### Scenario: Runtime includes enrichment fields

- **WHEN** runtime output includes `hunk_id`, `lane_id`, or `anchorable`
- **THEN** strict wire validation marks the output invalid because enrichment belongs downstream

### Requirement: Validity requires four signals

A runtime execution MUST be VALID only when the process exits zero, a non-empty output artifact exists, the artifact parses and validates against the supplied schema validator, and the combined run log contains the terminal completion marker `tokens used`. Optional structured or textual usage telemetry MUST NOT make an otherwise invalid run VALID, and unavailable telemetry MUST NOT make a valid run INVALID.

#### Scenario: Schema-valid artifact without completion marker

- **WHEN** Codex exits zero and writes valid JSON but its log lacks `tokens used`
- **THEN** the result is INVALID with reason `no_completion_marker`

#### Scenario: Process times out

- **WHEN** RVW deadline enforcement expires and returns a nonzero timeout result
- **THEN** the result is INVALID with reason `exit_nonzero:<code>` and has no promoted output

#### Scenario: Usage telemetry is absent

- **WHEN** a completed traditional log contains the completion marker but no
  parseable token count
- **THEN** the result can remain VALID and its optional token fields are absent

### Requirement: Invalidity is machine-readable

Every INVALID result MUST have no output, a non-empty machine-readable `invalid_reason`, and retained artifact diagnostics, while every VALID result MUST have validated non-empty output, no invalid reason, and no invalid diagnostic. Output classification MUST distinguish `missing`, `empty`, `unparseable`, and `schema-invalid`; process and completion failures MUST remain distinct from output-content failures.

#### Scenario: Artifact is missing

- **WHEN** a zero-exit execution creates no `out.json`
- **THEN** the result is INVALID with reason `missing` and cannot be represented as VALID

#### Scenario: Artifact is empty

- **WHEN** an execution creates a zero-byte `out.json`
- **THEN** the result is INVALID with reason `empty` rather than being treated as a valid empty response

#### Scenario: Artifact is malformed or violates its schema

- **WHEN** a non-empty `out.json` cannot be decoded as JSON or fails strict schema validation
- **THEN** the result is INVALID with reason `unparseable` or `schema-invalid` respectively

### Requirement: Runtime artifacts are persisted per replica

The Codex adapter MUST write `prompt.md`, `schema.json`, `out.json`, `run.log`,
and `usage.json` beneath an `r<replica>` artifact directory before or during
execution and MUST derive the replica number from that directory name.
`usage.json` MUST record model, reasoning effort, wall time, and final
completed/invalid/canceled state; token, turn, and tool-call fields MAY be
absent when telemetry is unavailable. Discovery and sampling MUST preserve the
existing lane-or-variant `r<replica>` path for a one-chunk plan and MUST insert
a `c<chunk>` directory immediately before `r<replica>` for a multi-chunk plan.

#### Scenario: Malformed run directory

- **WHEN** the adapter is given a directory not ending in `r<positive-integer>`
- **THEN** execution fails before assigning an ambiguous replica number

#### Scenario: One chunk preserves artifact paths

- **WHEN** a lane's diff fits in one chunk
- **THEN** its artifacts remain beneath `<lane>/r<replica>/` with no chunk directory

#### Scenario: Multiple chunks separate artifacts

- **WHEN** a lane's diff requires two chunks
- **THEN** its artifacts are separated beneath `<lane>/c1/r<replica>/` and `<lane>/c2/r<replica>/`

#### Scenario: Runtime is cancelled

- **WHEN** a runtime task is cancelled after its process starts
- **THEN** its process group is cleaned up, `usage.json` records `canceled`,
  and cancellation continues to the dispatcher

### Requirement: Raw execution supports stage-specific schemas and workdirs

The runtime protocol MUST provide `execute_raw` with a caller-supplied schema, validator, optional working directory, deadline, prompt, and artifact directory so adjudication and sampling can reuse the same validity contract.

#### Scenario: Adjudication reads checked-out source

- **WHEN** adjudication calls `execute_raw` with a provisioned repository directory
- **THEN** Codex runs read-only with that directory as its process working directory and validates the adjudication-specific output model

### Requirement: Codex execution is read-only and bounded

The Codex adapter SHALL invoke `codex exec` directly and MUST expose distinct
tool-less and agentic execution modes under the same explicit typed model and
reasoning policy. Tool-less mode MUST select the read-only sandbox, disable
shell, browser, computer, app, plugin, image, multi-agent, and collaboration
tools, disable rule loading and persisted sessions, and use strict structured
output. Agentic mode SHALL select the read-only sandbox and disable multi-agent
and collaboration modes while retaining source exploration for explicitly
expanded adjudication only. The adapter MUST capture its newly created process
group before awaiting the runtime and enforce each configured deadline by
cancelling its process-owning task. That task MUST terminate the complete
captured process group with TERM, wait no more than five seconds for the group
to disappear, and escalate to KILL. After KILL, it MUST wait no more than a
further five seconds for the captured group to disappear. If the group still
exists or cannot be verified because a probe receives `EPERM`, it MUST record
persistent or unverified cleanup in the run log and return so the original
cancellation or timeout classification can continue. Runtime identity and
usage MUST record the selected mode so resume cannot reuse a result from
another mode. The initial default policy MUST be `gpt-5.6-sol` with `max`
reasoning effort.

#### Scenario: Tool-less discovery execution

- **WHEN** DISCOVER starts a lane replica
- **THEN** its Codex command disables shell and other interactive tools, writes
  no persisted Codex session, and records zero tool calls in usage

#### Scenario: Expanded adjudication execution

- **WHEN** an initially UNCERTAIN candidate starts its one expanded pass
- **THEN** its Codex command uses agentic read-only mode and can inspect the
  provisioned checkout

#### Scenario: Deadline expires

- **WHEN** a run exceeds its configured deadline
- **THEN** RVW terminates and reaps the full runtime process group and classifies
  the run INVALID with reason `exit_nonzero:124`

#### Scenario: Runtime leader exits before its child

- **WHEN** TERM ends the runtime leader but a child in its captured process group
  remains alive
- **THEN** RVW detects the surviving group during the grace period, sends KILL,
  and returns after the group exits

#### Scenario: Process group persists after KILL

- **WHEN** the captured process group still appears to exist for five seconds
  after RVW sends KILL
- **THEN** RVW records a persistent-cleanup marker and does not wait
  indefinitely before returning the original cancellation or timeout result

#### Scenario: Process group cannot be verified after KILL

- **WHEN** the post-KILL process-group probe receives `EPERM`
- **THEN** RVW records an unverified-cleanup marker and returns the original
  cancellation or timeout result without propagating the probe exception

#### Scenario: Ambient configuration requests a different policy

- **WHEN** a host config selects another model or reasoning effort
- **THEN** an RVW Codex invocation still carries `--model gpt-5.6-sol` and an
  explicit `model_reasoning_effort="max"` override
