## 1. Regression Tests

- [x] 1.1 Add a failing regression proving two `RunStore.create` calls for the
  same target in the same second yield distinct run directories without
  raising.
- [x] 1.2 Add a failing regression proving run IDs remain `_SAFE_RUN_ID`-safe
  and `RunStore.open`-compatible with the sub-second component.
- [x] 1.3 Add a failing dispatch regression proving an all-INVALID retry
  leaves the initial wave's `prompt.md`, `run.log`, and output artifacts
  intact and writes replacement artifacts to a distinct directory.

## 2. Implementation

- [x] 2.1 Append the microsecond field to ordinary run IDs and resolve
  residual `FileExistsError` collisions by regenerating the identifier a
  bounded number of times.
- [x] 2.2 Route replacement-wave run directories beneath a `retry/` directory
  whose final component remains `r{replica}`.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the reporting and discovery main specs and contexts with
  the implemented behavior.
- [x] 3.2 Run the five required bare verification gates and inspect the final
  diff for scope drift.
