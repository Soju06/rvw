## MODIFIED Requirements

### Requirement: Codex execution is read-only and bounded

The Codex adapter SHALL invoke `codex exec` through a foreground timeout,
SHALL select the read-only sandbox, and SHALL disable multi-agent and
collaboration modes for each runtime execution. Every invocation MUST receive a
typed explicit runtime policy that supplies the Codex model through `--model`
and the reasoning effort through the `model_reasoning_effort` TOML override;
it MUST NOT inherit either value from ambient Codex configuration. The initial
default policy MUST be `gpt-5.6-sol` with `max` reasoning effort.

#### Scenario: Deadline expires

- **WHEN** a run exceeds its configured deadline
- **THEN** the wrapper sends TERM, allows a 30-second kill-after window, and
  the nonzero result is classified INVALID

#### Scenario: Ambient configuration requests a different policy

- **WHEN** a host config selects another model or reasoning effort
- **THEN** an RVW Codex invocation still carries `--model gpt-5.6-sol` and an
  explicit `model_reasoning_effort="max"` override
