## MODIFIED Requirements

### Requirement: Raw execution supports stage-specific schemas and workdirs

The runtime protocol MUST provide `execute_raw` with a caller-supplied schema, validator, optional working directory, deadline, prompt, and artifact directory so adjudication and sampling can reuse the same validity contract.

#### Scenario: Adjudication reads checked-out source

- **WHEN** adjudication calls `execute_raw` with a provisioned repository directory
- **THEN** Codex uses the configured sandbox mode with that directory as its process working directory and validates the adjudication-specific output model

### Requirement: Discovery execution uses its verified checkout

The runtime protocol MUST accept a caller-supplied workdir for lane execution, and agentic discovery MUST execute plain `codex exec` with that workdir set to the verified checkout. The execution MUST honor the selected sandbox mode and its surface isolation boundary, and the command MUST NOT use `codex exec review`.

#### Scenario: Agentic lane explores repository context

- **WHEN** discovery dispatches an agentic lane for a verified target checkout
- **THEN** plain structured `codex exec` runs in the selected sandbox mode with that checkout as its process working directory

### Requirement: Codex execution is read-only and bounded

The Codex adapter SHALL invoke `codex exec` directly and MUST expose distinct
tool-less and agentic execution modes under the same explicit typed model and
reasoning policy. Every mode MUST pass `--sandbox` with the value selected by
`RVW_CODEX_SANDBOX`, which MUST accept only `read-only` or
`danger-full-access`, MUST default to `read-only`, and MUST reject any other
value before spawning Codex. Tool-less mode MUST disable shell, browser,
computer, app, plugin, image, multi-agent, and collaboration tools, disable
rule loading and persisted sessions, and use strict structured output. Agentic
mode MUST disable multi-agent and collaboration modes while retaining source
exploration for agentic discovery and explicitly expanded adjudication. The
root project container MUST select `danger-full-access` because measured nested
bubblewrap namespace creation is unavailable there; this fallback MUST NOT
change the host default, and the read-only-mounted root container MUST remain the
isolation boundary. The App Sandbox MUST explicitly select and record its
effective sandbox mode and MUST NOT describe its checkout as read-only unless
that property is enforced by its own isolation boundary. The adapter SHALL never invoke `codex exec review`. The
adapter MUST capture its newly created process
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

#### Scenario: Tool-less inline discovery execution

- **WHEN** inline DISCOVER starts a lane replica
- **THEN** its Codex command disables shell and other interactive tools, writes
  no persisted Codex session, and records zero tool calls in usage

#### Scenario: Agentic discovery execution

- **WHEN** agentic DISCOVER starts a lane replica in its verified checkout
- **THEN** its Codex command uses bounded agentic mode with the configured sandbox selection and can inspect
  the provisioned checkout

#### Scenario: Initial adjudication execution

- **WHEN** an initial adjudication pass evaluates candidates from the supplied
  reviewed diff
- **THEN** its Codex command uses tool-less mode with the configured sandbox selection

#### Scenario: Expanded adjudication execution

- **WHEN** an initially UNCERTAIN candidate starts its one expanded pass
- **THEN** its Codex command uses agentic mode with the configured sandbox selection and can inspect the
  provisioned checkout

#### Scenario: Host runtime uses its default sandbox

- **WHEN** rvw executes Codex without `RVW_CODEX_SANDBOX`
- **THEN** plain Codex execution receives `--sandbox read-only`

#### Scenario: Container runtime uses its measured fallback

- **WHEN** the project container executes Codex with `RVW_CODEX_SANDBOX=danger-full-access`
- **THEN** plain Codex execution receives `--sandbox danger-full-access` inside the container boundary

#### Scenario: Sandbox selector is unsupported

- **WHEN** `RVW_CODEX_SANDBOX` contains any other value
- **THEN** runtime execution fails before Codex is spawned

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

#### Scenario: Discovery uses structured output

- **WHEN** a lane runtime is invoked
- **THEN** plain `codex exec` receives the lane's closed-enum output schema and custom prompt

## ADDED Requirements

### Requirement: Policy-gated execution owns a versioned process envelope

Python MUST initialize `process.json` before target resolution and finalize it for every `run` or `auto` termination for which the artifact directory can be written. Its strict version-1 schema MUST contain `schema_version: 1`, string `run_id`, `target` with nullable `repo`, `pr`, `base`, and `head`, `status` in `pass|block|invalid|infra_failed`, the corresponding integer `exit_code` in `0|1|2|3`, nonnegative integer `duration_ms`, canonical argument-array `command`, `effective_policy` with nullable `source` and `path`, a `lane_sources` count mapping, `runtime` effective settings, nullable `failure` with `code` and `detail`, an `artifacts` array of relative `path` and nonnegative `size_bytes` records, and nullable `sdk_observations` with nullable `exit_code`, `signal`, `duration_ms`, and wrapper `command`. Policy source MUST be `explicit`, `repository`, `external`, or `package` when known. Runtime settings MUST include `replicas`, `adjudicate_replicas`, `concurrency`, `deadline`, `discovery_mode`, `publish`, `host_concurrency`, and `sandbox`. Before completion, the envelope MUST default to `infra_failed`, exit 3, and failure `execution_incomplete`; it MUST never predeclare PASS. Adapters MUST consume this envelope rather than manufacture a competing result format.

#### Scenario: Resolution fails before discovery

- **WHEN** target resolution fails after artifact-root initialization
- **THEN** `process.json` still identifies the run, selected settings, failure and reserved exit code, with unknown target and policy fields null

#### Scenario: Execution is forcibly stopped

- **WHEN** an adapter observes forced termination after Python initialized its contract
- **THEN** the incomplete envelope remains a failure and the adapter merges SDK-observed supplemental termination evidence into that same contract without inventing a policy verdict

### Requirement: Every terminal execution retains shared diagnostics

Python MUST write top-level `run.log` and `environment.txt` beside its process and summary contracts. Diagnostics MUST redact credentials and MUST describe effective runtime configuration without copying credential values. Finalization MUST retain already produced stage and runtime artifacts on failure. A supervisor MUST attempt the same diagnostic persistence before destruction for normal completion, timeout, process start failure, process disappearance, and supersession; persistence errors MUST not suppress the original terminal reason or prevent other diagnostics from being attempted.

#### Scenario: Publication fails after report generation

- **WHEN** publication raises after stage artifacts were saved
- **THEN** those files and the log, environment, process, and summary contracts remain discoverable under the selected output directory

#### Scenario: One diagnostic cannot be read

- **WHEN** an adapter cannot read a particular terminal diagnostic
- **THEN** it attempts the remaining diagnostics and records the failed persistence operation before Sandbox destruction
