## MODIFIED Requirements

### Requirement: Codex execution is read-only and bounded

The Codex adapter SHALL invoke `codex exec` through a foreground timeout,
SHALL select the read-only sandbox, and SHALL disable multi-agent and
collaboration modes for each runtime execution. Every invocation MUST receive a
typed explicit runtime policy that supplies the Codex model through `--model`
and the reasoning effort through the `model_reasoning_effort` TOML override;
it MUST NOT inherit either value from ambient Codex configuration. The initial
default policy MUST be `gpt-5.6-sol` with `max` reasoning effort.

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
- **THEN** the wrapper sends TERM, allows a 30-second kill-after window, and
  the nonzero result is classified INVALID

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
