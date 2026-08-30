## 1. Regression Tests

- [x] 1.1 Add a failing regression proving a retried lane-chunk's coverage
  row records the initial attempt's INVALID status and reason plus the retry
  attempt's outcome, in order.
- [x] 1.2 Add a failing regression proving non-retried runs carry exactly one
  attempt record mirroring the row.
- [x] 1.3 Add a failing round-trip regression proving attempt records persist
  through `save_discover`/`load_discover`.
- [x] 1.4 Add a failing legacy-load regression proving a `discover.json`
  without attempt records loads with empty attempt history.

## 2. Implementation

- [x] 2.1 Add the strict `RunAttempt` model and the `attempts` field on
  `RunCoverage` with safe defaults and invariant validation.
- [x] 2.2 Expose initial-wave results from `dispatch` for retried keys and
  build ordered attempt records in `discover`.
- [x] 2.3 Persist and leniently load attempt records in the run store.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the discovery main spec and context with the
  implemented behavior.
- [x] 3.2 Run the five required bare verification gates and inspect the final
  diff for scope drift.
