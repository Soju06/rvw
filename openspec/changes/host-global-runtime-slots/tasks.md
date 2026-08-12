## 1. Regression Tests

- [x] 1.1 Add a failing regression proving in-flight runtime executions never
  exceed the host cap when it is lower than the process semaphore.
- [x] 1.2 Add a failing regression proving slots release on successful
  completion, on runtime exception, and on task cancellation.
- [x] 1.3 Add a failing regression proving two gate instances sharing one
  slot root contend for the same slots (cross-process simulation).
- [x] 1.4 Add a failing regression proving `RVW_HOST_CONCURRENCY=0` bypasses
  the gate and invalid values are rejected before runtime execution.
- [x] 1.5 Add a failing regression proving a symlinked slot root fails
  closed.

## 2. Implementation

- [x] 2.1 Add the flock slot-gate module (lazy 0700 creation, cap-sharded
  directory, random-start non-blocking scan, blocking fallback, thread
  offload, close-on-release).
- [x] 2.2 Read and validate `RVW_HOST_CONCURRENCY` once per command start and
  thread the gate through dispatch, adjudication, sampling, and stack
  presence adjudication around each runtime execution.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the discovery and operation-modes main specs and
  contexts with the implemented behavior.
- [x] 3.2 Run the five required bare verification gates and inspect the final
  diff for scope drift.
