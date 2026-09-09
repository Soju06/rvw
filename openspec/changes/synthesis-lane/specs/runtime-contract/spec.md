## ADDED Requirements

### Requirement: Execution summaries retain synthesis facts

The strict summary.json contract MUST include `synthesis` with `status`, `model`, `reasoning_effort`, `wall_seconds`, and `tool_calls`. Status MUST be `ok` or `fallback:<reason>`. Model and effort MUST identify the runtime policy when invoked; wall seconds and tool calls MUST aggregate attempted synthesis executions, using null for unavailable telemetry. Legacy summaries without synthesis MUST remain readable with an explicit unavailable fallback. These facts MUST NOT change review status or judgments.

#### Scenario: Successful retry

- **WHEN** synthesis produces one invalid output followed by valid output
- **THEN** status is ok and synthesis telemetry includes both attempts

#### Scenario: Legacy summary

- **WHEN** an adapter reads a summary with no synthesis field
- **THEN** parsing succeeds and no successful synthesis is inferred

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
another mode. The packaged default policy MUST remain `gpt-6-astra` with
`high` reasoning effort. The effective model and reasoning effort MUST be
resolved once per command from the explicit `--model` and `--reasoning-effort`
options, then `RVW_CODEX_MODEL` and `RVW_CODEX_REASONING_EFFORT`, then the
packaged default, and MUST be passed to every review runtime the command
constructs (discovery with its retry and coverage redispatch, initial and
expanded adjudication, synthesis, stack presence, sample, and re-adjudication) so none of
them falls back to the packaged default on its own; only the publication
language rewriter keeps the packaged default. The effective
reasoning effort MUST be one of the Codex 0.152.0 values `none`, `minimal`,
`low`, `medium`, `high`, `xhigh`, `max`, `ultra`, or `persistent`; the
effective model MUST be non-empty after trimming; a present but malformed
option or environment value MUST fail closed before any runtime work. The
effective values MUST be recorded in `usage.json`, `process.json`
(`runtime.model` and `runtime.reasoning_effort`), and `environment.txt`. Every
mode MUST pass an explicit `model_reasoning_summary` override, whose default is
`detailed`, without changing the model or reasoning effort. The adapter MUST
race every execution against a no-output watchdog
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
`usage.json`, `process.json`, and `environment.txt`. The adapter MUST spawn Codex
with `RVW_PHASE=review` and `GIT_ALLOW_PROTOCOL=none` in the child environment
and MUST NOT set `RVW_PHASE=review` in its own process, so the image's review-phase
shims and git's transport check govern model-driven tool commands while the CLI's
own target resolution and publication keep their access. Checkout provisioning
MUST run its own `git` and `gh` commands with `RVW_PHASE=checkout`.

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

#### Scenario: Runtime child environment carries the review phase

- **WHEN** the adapter spawns Codex
- **THEN** the child environment contains `RVW_PHASE=review` and
  `GIT_ALLOW_PROTOCOL=none` while the rvw process environment does not

#### Scenario: Checkout commands carry the checkout phase

- **WHEN** rvw provisions or verifies a checkout with its own `git` and `gh` commands
- **THEN** those commands run with `RVW_PHASE=checkout` and otherwise inherit the
  process environment

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

- **WHEN** a host config selects another model or reasoning effort and rvw
  receives no `--model`, `--reasoning-effort`, `RVW_CODEX_MODEL`, or
  `RVW_CODEX_REASONING_EFFORT` override
- **THEN** an RVW Codex invocation still carries `--model gpt-6-astra` and an
  explicit `model_reasoning_effort="high"` override

#### Scenario: Override resolution follows the documented precedence

- **WHEN** a command is invoked with `--reasoning-effort high` while
  `RVW_CODEX_REASONING_EFFORT` is `medium` and `RVW_CODEX_MODEL` is
  `gpt-6-astra`
- **THEN** every runtime the command constructs carries `--model gpt-6-astra`
  and an explicit `model_reasoning_effort="high"` override, and each
  `usage.json` records `model: gpt-6-astra` and `reasoning_effort: high`

#### Scenario: Environment override is malformed

- **WHEN** `RVW_CODEX_REASONING_EFFORT` is `maximum` or `RVW_CODEX_MODEL` is
  whitespace-only
- **THEN** the command fails closed naming the variable, listing the allowed
  effort values for the effort case, and no runtime is constructed or spawned

#### Scenario: Discovery uses structured output

- **WHEN** a lane runtime is invoked
- **THEN** plain `codex exec` receives the lane's closed-enum output schema and custom prompt
