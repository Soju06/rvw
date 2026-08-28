## 1. Regression Coverage

- [x] 1.1 Add a failing runtime-command regression proving Codex is invoked
  directly, then verify it fails against the foreground-wrapper implementation.
- [x] 1.2 Add a deterministic deadline regression proving adapter timeout
  cancels the spawned task and persists `exit_nonzero:124`, verified by
  `tests/test_runtime_codex.py`.

## 2. Runtime Deadline Ownership

- [x] 2.1 Remove the external timeout command prefix and enforce the selected
  deadline around the process-owning spawn task, verified by the focused
  runtime-adapter test suite.
- [x] 2.2 Preserve caller cancellation and invalid usage behavior while mapping
  adapter deadline expiry to `exit_nonzero:124`, verified by the focused
  runtime-adapter test suite.

## 3. Specification and Verification

- [x] 3.1 Synchronize the runtime-contract main spec and context with
  adapter-owned process-tree cleanup.
- [x] 3.2 Run OpenSpec validation and all required bare verification gates.
