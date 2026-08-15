## 1. Regression Tests

- [x] 1.1 Add failing callable regressions proving all six runtime deadline defaults use the shared 600-second value.
- [x] 1.2 Add failing command-path regressions proving the default and explicit deadline reach review, gate, auto, sample, stack review, and stack presence runtime paths.
- [x] 1.3 Add failing Typer validation coverage proving deadline values 0 and 1801 are rejected before runtime work.
- [x] 1.4 Preserve deterministic regressions proving expanded adjudication and stack-presence passes receive twice the selected base deadline.

## 2. Runtime and CLI Implementation

- [x] 2.1 Define shared default and maximum deadline constants and replace all six callable default literals.
- [x] 2.2 Thread the base deadline through the shared pipeline to discovery and adjudication.
- [x] 2.3 Add the bounded `--deadline` option to review, auto, gate, stack review, and sample and propagate it through every helper and direct runtime path.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the discovery and operation-modes main specs and contexts with the implemented behavior.
- [x] 3.2 Run focused offline regressions and inspect the final diff for incomplete wiring, scope drift, and lockfile changes.
- [x] 3.3 Run the required bare verification gates plus change-delta validation.
