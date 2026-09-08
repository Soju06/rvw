## MODIFIED Requirements

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
reasoning effort. Every mode MUST pass an explicit `model_reasoning_summary`
override, whose default is `detailed`, without changing the model or reasoning
effort. The adapter MUST race every execution against a no-output watchdog
that polls the combined `run.log` size every few seconds, MUST cancel the
process-owning task through the same terminate-and-reap path when the log has
not grown for the configured `no_output_seconds`, and MUST classify that run
INVALID with reason `no_output_after:<N>s`. Growth MUST be measured on the
combined stdout and stderr log, so a runtime that keeps printing reconnect
notices is alive. The deadline race is unchanged and whichever fires first
wins: a deadline kill remains `exit_nonzero:124`, and `no_output_after:*` is a
distinct transient reason. `no_output_seconds` MUST be configured per runtime
from the CLI `--no-output-timeout` option, then `RVW_NO_OUTPUT_SECONDS`, then a
default of 660 seconds, MUST be rejected when below 1, and MUST be recorded in
`usage.json`, `process.json`, and `environment.txt`.

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

#### Scenario: Runtime produces no output

- **WHEN** a runtime prints its banner and prompt echo and then writes nothing
  for `no_output_seconds`
- **THEN** RVW terminates and reaps the full runtime process group and classifies
  the run INVALID with reason `no_output_after:<N>s`

#### Scenario: Runtime keeps reconnecting

- **WHEN** a runtime writes reconnect notices to stderr within every
  `no_output_seconds` window
- **THEN** the combined log keeps growing and the watchdog does not terminate it

#### Scenario: Silence begins after the deadline boundary

- **WHEN** a runtime falls silent when fewer than `no_output_seconds` remain
  before its configured deadline
- **THEN** the deadline fires first and the run is INVALID with reason
  `exit_nonzero:124`

#### Scenario: Reasoning summaries are requested

- **WHEN** any RVW Codex invocation is built
- **THEN** its argv carries `model_reasoning_summary="detailed"` after the
  reasoning-effort override and its `usage.json` records `reasoning_summary`

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

### Requirement: Policy-gated execution owns a versioned process envelope

Python MUST initialize `process.json` before target resolution and finalize it for every `run` or `auto` termination for which the artifact directory can be written. Its strict version-1 schema MUST contain `schema_version: 1`, string `run_id`, `target` with nullable `repo`, `pr`, `base`, and `head`, `status` in `pass|block|invalid|infra_failed`, the corresponding integer `exit_code` in `0|1|2|3`, nonnegative integer `duration_ms`, canonical argument-array `command`, `effective_policy` with nullable `source` and `path`, a `lane_sources` count mapping, `runtime` effective settings, nullable `failure` with `code` and `detail`, resolved `presentation`, nullable nonempty-string `publication_failure` defaulting to null, boolean `language_fallback_used` defaulting to false, an `artifacts` array of relative `path` and nonnegative `size_bytes` records, and nullable `sdk_observations` with nullable `exit_code`, `signal`, `duration_ms`, and wrapper `command`. Policy source MUST be `explicit`, `repository`, `external`, or `package` when known. Runtime settings MUST include `replicas`, `adjudicate_replicas`, `concurrency`, `deadline`, `discovery_mode`, `publish`, `host_concurrency`, `sandbox`, `no_output_seconds`, and `reasoning_summary`; adapters MUST accept envelopes persisted before the last two existed and MUST reject a present `no_output_seconds` below 1 or an empty `reasoning_summary`. Before completion, the envelope MUST default to `infra_failed`, exit 3, and failure `execution_incomplete`; it MUST never predeclare PASS. Adapters MUST consume this envelope rather than manufacture a competing result format.

#### Scenario: Resolution fails before discovery

- **WHEN** target resolution fails after artifact-root initialization
- **THEN** `process.json` still identifies the run, selected settings, failure and reserved exit code, with unknown target and policy fields null

#### Scenario: Execution is forcibly stopped

- **WHEN** an adapter observes forced termination after Python initialized its contract
- **THEN** the incomplete envelope remains a failure and the adapter merges SDK-observed supplemental termination evidence into that same contract without inventing a policy verdict

#### Scenario: Legacy envelope omits watchdog settings

- **WHEN** an adapter parses a `process.json` whose `runtime` lacks `no_output_seconds` and `reasoning_summary`
- **THEN** parsing succeeds, while an envelope carrying `no_output_seconds: 0` or an empty `reasoning_summary` is rejected as invalid runtime settings

### Requirement: Runtime artifacts are persisted per replica

The Codex adapter MUST write `prompt.md`, `schema.json`, `out.json`, `run.log`,
and `usage.json` beneath an `r<replica>` artifact directory before or during
execution and MUST derive the replica number from that directory name.
`usage.json` MUST record model, reasoning effort, the reasoning summary
setting, the no-output watchdog setting, wall time, and final
completed/invalid/canceled state. It MUST also record `tool_calls`, counted as
the lines of `run.log` that are exactly the `exec` item header Codex prints
before each tool command, and `assistant_messages`, counted as the lines that
are exactly the `codex` item header printed before each assistant message; a
tool-less run MUST record zero `tool_calls`, and both counts are optional
telemetry that MUST be absent when the log cannot be read (except the tool-less
zero) and MUST never affect validity. Token, turn, and tool-call fields MAY be
absent when telemetry is unavailable, and usage artifacts persisted before the
summary, watchdog, and telemetry fields existed MUST load with those fields
absent. Discovery and sampling MUST preserve the
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

#### Scenario: Legacy usage artifact loads

- **WHEN** a `usage.json` persisted before the reasoning summary, watchdog,
  and telemetry fields is loaded
- **THEN** loading succeeds with those fields absent

#### Scenario: Agentic run with three tool commands

- **WHEN** an agentic run's `run.log` holds three `exec` headers and three
  `codex` headers
- **THEN** its `usage.json` records `tool_calls: 3` and
  `assistant_messages: 3`, and validity is decided only by the existing signals

#### Scenario: Tool-less run records no tool commands

- **WHEN** a tool-less run completes
- **THEN** its `usage.json` records `tool_calls: 0` and counts its
  `assistant_messages` from the `codex` headers
