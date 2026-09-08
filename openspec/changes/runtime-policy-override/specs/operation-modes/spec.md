## ADDED Requirements

### Requirement: Runtime-executing commands expose the Codex model and reasoning effort

The `review`, `run`, `auto`, `gate`, `stack review`, `sample`, and `adjudicate` commands MUST expose `--model` and `--reasoning-effort`. Each field MUST be resolved once at command start with the precedence explicit option, then `RVW_CODEX_MODEL` or `RVW_CODEX_REASONING_EFFORT`, then the packaged default of `gpt-5.6-sol` and `max`; an explicit option MUST suppress consultation of its environment variable. The effective reasoning effort MUST be one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, or `persistent` after trimming, and the effective model MUST be non-empty after trimming. A malformed option or a present but malformed environment value MUST fail closed before any runtime work: `run` and `auto` MUST finalize `process.json` as `invalid_configuration` with exit 2 and a detail naming the option or variable, and the other commands MUST exit 2 naming the option or variable. The resolved policy MUST be propagated to every discovery, retry, coverage-redispatch, adjudication initial and expanded, stack-presence, sample, and re-adjudication runtime the command constructs. `run` and `auto` MUST record the effective values in `process.json` under `runtime.model` and `runtime.reasoning_effort`, in the canonical command as `--model <model> --reasoning-effort <effort>`, and in `environment.txt`.

#### Scenario: Default is recorded

- **WHEN** `rvw run` is invoked without `--model` or `--reasoning-effort` and without `RVW_CODEX_MODEL` or `RVW_CODEX_REASONING_EFFORT`
- **THEN** every runtime it starts uses `gpt-5.6-sol` at `max`, `process.json` records `runtime.model: gpt-5.6-sol` and `runtime.reasoning_effort: max`, and the canonical command contains `--model gpt-5.6-sol --reasoning-effort max`

#### Scenario: Explicit option is recorded

- **WHEN** `rvw run` is invoked with `--model gpt-6-astra --reasoning-effort high`
- **THEN** every runtime it starts carries `--model gpt-6-astra` and `model_reasoning_effort="high"`, the canonical command contains `--model gpt-6-astra --reasoning-effort high`, and `environment.txt` contains `model=gpt-6-astra` and `reasoning_effort=high`

#### Scenario: Environment supplies the value

- **WHEN** `review`, `run`, `auto`, `gate`, `stack review`, `sample`, or `adjudicate` is invoked without the options while `RVW_CODEX_REASONING_EFFORT` is `medium`
- **THEN** every runtime it starts uses `gpt-5.6-sol` at `medium`, and `run` and `auto` record `runtime.reasoning_effort: medium`

#### Scenario: Environment value is malformed

- **WHEN** `RVW_CODEX_REASONING_EFFORT` is `maximum` or `RVW_CODEX_MODEL` is empty
- **THEN** `run` and `auto` finalize `process.json` with `invalid_configuration` and exit 2 naming the variable, and `review`, `gate`, `stack review`, `sample`, and `adjudicate` exit 2 naming the variable before any runtime work

#### Scenario: Explicit option is malformed

- **WHEN** any of the seven commands is invoked with `--reasoning-effort maximum` or `--model ' '`
- **THEN** the command fails closed before any runtime work with a message naming the option and, for the effort, listing the nine allowed values; `run` and `auto` record `invalid_configuration` with exit 2
