## Why

Every discovery and adjudication runtime runs `gpt-5.6-sol` at reasoning effort `max`, hardcoded as `DEFAULT_CODEX_RUNTIME_POLICY`. Four consecutive production App runs on the consuming repository (rvw 0.15.0 and 0.16.0, `--deadline 900`) showed the same three base lanes, `correctness`, `hygiene`, and `test-integrity`, hitting the 900 s deadline on every attempt. Each dead lane had announced that all changed regions were covered and that a final evidence pass was underway, then kept calling tools until the kill: 35 to 94 tool calls per dead lane, against 5 to 19 for the lanes that finished. The prompt budget contract added in 0.15.0 (wall budget, coverage-first, a tool-call budget of 40, no remote access) did not change this. The owner wants to A/B the reasoning effort (`medium`, `high`) and the model (a `gpt-6` variant) against the current default before touching lane prompts, because the post-coverage exploration habit may be model x effort behaviour rather than prompt wording. That requires changing the policy per run without a code change, on both the CLI and the GitHub App path, and having the effective values in every artifact so the cells can be told apart afterwards.

## What Changes

- The Codex model and reasoning effort become overridable per run with the precedence explicit CLI option > environment variable (`RVW_CODEX_MODEL`, `RVW_CODEX_REASONING_EFFORT`) > packaged default. The packaged default stays exactly `gpt-5.6-sol` / `max`; nothing changes for a run that sets neither.
- `review`, `run`, `auto`, `gate`, `stack review`, `sample`, and `adjudicate` expose `--model` and `--reasoning-effort`. The policy is resolved once per command and passed to every runtime the command constructs (discovery, retry, coverage redispatch, adjudication initial and expanded, stack presence, sample, re-adjudication), so no runtime falls back to the packaged default on its own. The publication language rewriter keeps the packaged default.
- The reasoning effort is validated against the nine Codex 0.152.0 `ReasoningEffort` values (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `persistent`); the model must be non-empty after trimming. A malformed option or a present but malformed environment value fails closed before any runtime work: `run` and `auto` finalize `process.json` as `invalid_configuration` with exit 2, the other commands exit 2 naming the option or variable.
- The effective values are recorded in `usage.json` (already), `process.json` under `runtime.model` and `runtime.reasoning_effort`, `environment.txt` as `model=` and `reasoning_effort=`, and in the canonical command of `run` and `auto` as `--model <m> --reasoning-effort <e>`.
- The Worker reads the optional vars `RVW_CODEX_MODEL` and `RVW_CODEX_REASONING_EFFORT` and, when set, appends shell-quoted `--model` / `--reasoning-effort` to the `rvw run` invocation; when unset it passes nothing. A present but empty or off-enum var fails closed with `config_invalid`. The committed Wrangler configuration does not set them. The Worker parser accepts the two new runtime fields, and the check `text` carries `runtime.model` and `runtime.reasoning_effort` from `process.json`.
- The spike `/start` endpoint accepts an optional JSON body `{"model": ..., "reasoning_effort": ...}` (body beats Worker var beats default; unknown keys, empty model, off-enum effort, and malformed JSON are 400 without a sandbox), echoes the effective overrides in its 202 response, and the driver script sends that body when the same variables are set in its own environment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtime-contract`: the resolved model and reasoning-effort policy, its precedence, the effort enum, fail-closed validation, artifact recording, and the two new process-envelope runtime fields.
- `operation-modes`: the `--model` and `--reasoning-effort` options on the seven runtime-executing commands, `RVW_CODEX_MODEL` and `RVW_CODEX_REASONING_EFFORT`, and their propagation and recording.
- `cloud-app-platform`: the optional Worker vars, the spike `/start` body, and the check-text runtime facts.

## Impact

- `src/rvw/runtime_policy.py` (`REASONING_EFFORT_VALUES`, `CODEX_MODEL_ENV`, `REASONING_EFFORT_ENV`, `resolve_codex_runtime_policy`), `src/rvw/cli.py` (options, `_command_runtime_policy`, `_execute_pipeline` and the pipeline helpers, `_run_command` configuration stage), `src/rvw/summary.py` (`RuntimeSettings.model`, `RuntimeSettings.reasoning_effort`), `src/rvw/resources/schemas/process.schema.json`, and their tests.
- `cloud/worker/src/sandbox-auth.ts`, `config.ts`, `review-job.ts`, `review-job-contract.ts`, `spike-contract.ts`, `routes.ts`, `env.d.ts`, their tests, `cloud/README.md`, and `cloud/scripts/drive-spike.sh`. `cloud/wrangler.jsonc` is unchanged.
- Main specs and `context.md` for `runtime-contract`, `operation-modes`, and `cloud-app-platform`.
