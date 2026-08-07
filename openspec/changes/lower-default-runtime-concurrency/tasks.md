## 1. Regression Tests

- [x] 1.1 Add failing callable regressions proving every runtime concurrency default is 8.
- [x] 1.2 Add failing CLI regressions proving the default and explicit review concurrency reach dispatch and adjudication.
- [x] 1.3 Add failing Typer validation coverage proving `--concurrency 0` is rejected before execution.
- [x] 1.4 Add failing command-path regressions for auto, target-mode gate, sample, and stack review propagation.

## 2. Runtime and CLI Implementation

- [x] 2.1 Define the shared default of 8 and update discovery, adjudication, sampling, and stack presence semaphore inputs and validation.
- [x] 2.2 Thread concurrency through the shared pipeline to discovery and adjudication.
- [x] 2.3 Add the positive `--concurrency` option to review, auto, gate, stack review, and sample and propagate it through their helpers.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the discovery and operation-modes main specs and contexts with the implemented behavior.
- [x] 3.2 Run focused offline regressions and inspect the final diff for scope and lockfile drift.
- [x] 3.3 Run the five required bare verification gates and restore `uv.lock` if type checking changes it.
