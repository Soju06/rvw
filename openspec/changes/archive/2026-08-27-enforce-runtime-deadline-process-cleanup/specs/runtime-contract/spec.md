## MODIFIED Requirements

### Requirement: Codex execution is read-only and bounded

The Codex adapter SHALL invoke `codex exec` directly, SHALL select the
read-only sandbox, and SHALL disable multi-agent and collaboration modes for
each runtime execution. The adapter MUST enforce each configured deadline by
cancelling its process-owning task; that task MUST terminate the full runtime
process group with TERM, wait no more than five seconds, and escalate to KILL
before the timeout result is returned. Every invocation MUST receive a typed
explicit runtime policy that supplies the Codex model through `--model` and the
reasoning effort through the `model_reasoning_effort` TOML override; it MUST NOT
inherit either value from ambient Codex configuration. The initial default
policy MUST be `gpt-5.6-sol` with `max` reasoning effort.

#### Scenario: Deadline expires

- **WHEN** a run exceeds its configured deadline
- **THEN** RVW terminates and reaps the full runtime process group and classifies
  the run INVALID with reason `exit_nonzero:124`

#### Scenario: Runtime ignores graceful termination

- **WHEN** the runtime process group remains alive for five seconds after RVW
  sends TERM at deadline expiry
- **THEN** RVW sends KILL to that process group and waits for its process owner
  to exit before returning the INVALID timeout result

#### Scenario: Ambient configuration requests a different policy

- **WHEN** a host config selects another model or reasoning effort
- **THEN** an RVW Codex invocation still carries `--model gpt-5.6-sol` and an
  explicit `model_reasoning_effort="max"` override
