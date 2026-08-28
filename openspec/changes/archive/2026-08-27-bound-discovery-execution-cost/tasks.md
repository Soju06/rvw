## 1. Regression Tests

- [x] 1.1 Add failing planner/CLI regressions for exact initial prompt-character
  totals, initial/retry run accounting, and the default runtime profile shown by
  `rvw plan`.
- [x] 1.2 Add failing CLI regressions for `--discovery-replicas`, deprecated
  `--replicas`, conflicting values, the retry-upper-bound ceiling, and all
  explicit-heavy acknowledgement conditions.
- [x] 1.3 Add failing regressions proving the common execution seam rejects a
  required acknowledgement before runtime execution and every
  discovery-starting command forwards the explicit cost controls.
- [x] 1.4 Add a failing Codex adapter regression proving the selected model and
  `model_reasoning_effort` are explicit command arguments.

## 2. Implementation

- [x] 2.1 Add typed runtime policy and discovery preflight models with a
  12-run default ceiling and stable acknowledgement reasons.
- [x] 2.2 Extract and use the shared pure discovery planner from discovery,
  CLI plan rendering, and execution preflight.
- [x] 2.3 Add the formal replica option, legacy warning, ceiling, and
  `--allow-heavy-discovery` to every discovery-starting command without
  affecting sample's unrelated replica option.
- [x] 2.4 Enforce preflight before the common pipeline starts and render its
  accounting in human and JSON plan output.
- [x] 2.5 Make CodexRuntime render model and reasoning overrides from the typed
  policy for every runtime path.

## 3. Specification and Verification

- [x] 3.1 Synchronize operation-modes, discovery, and runtime-contract main
  specs and contexts with the implemented contract.
- [x] 3.2 Run focused offline tests, inspect the diff for external registry,
  persisted-schema, lockfile, and scope drift, and run change validation.

- [x] 3.3 Run all required bare repository verification gates.

## Verification

The local `~/.local/bin/uv` 0.9.26 process was SIGKILLed on `uv run` in this
environment. With the compatible Homebrew `uv` 0.12.0 resolved first on PATH,
the required bare `uv run` commands completed successfully: ruff check,
formatter check, ty, and the offline suite (`466 passed`, `4 skipped`, `3
deselected`). No repository or global tool configuration was changed.
