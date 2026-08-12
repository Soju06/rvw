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
  directory, random-start non-blocking scan, cancellable jittered polling,
  close-on-release).
- [x] 2.2 Read and validate `RVW_HOST_CONCURRENCY` once per command start and
  thread the gate through dispatch, adjudication, sampling, and stack
  presence adjudication around each runtime execution.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the discovery and operation-modes main specs and
  contexts with the implemented behavior.
- [x] 3.2 Run the five required bare verification gates and inspect the final
  diff for scope drift.

## 4. Adversarial Review Remediation

- [x] 4.1 Extend the operation-modes delta and synchronized main
  specification/context for Linux runtime-child parent-death coupling, strict
  slot-directory permissions, descriptor-relative opens, mandatory
  `O_NOFOLLOW`, and the accepted design dispositions.
- [x] 4.2 Add offline Linux regression coverage proving a runtime child exits
  after its spawning rvw process receives `SIGKILL`.
- [x] 4.3 Add real cross-process regressions proving a live holder blocks
  non-blocking acquisition and `SIGKILL` releases its flock.
- [x] 4.4 Add regressions for pre-existing directory mode enforcement,
  descriptor-relative slot opens, and missing `O_NOFOLLOW` support.
- [x] 4.5 Implement the Linux parent-death signal and hardened descriptor-based
  host-slot directory/file handling.
- [x] 4.6 Run every required bare verification gate and inspect the final diff
  for scope drift, including `uv.lock` and the external runtime registry.

## 5. Adversarial Review Remediation Round 2

- [x] 5.1 Replace thread-unsafe Linux `preexec_fn` parent-death setup with the
  exec-side `setpriv --pdeathsig SIGTERM` wrapper, fail closed when unavailable,
  and adapt the parent-SIGKILL regression.
- [x] 5.2 Add a failing cancellation regression and ensure a spawned runtime
  child is terminated and reaped before exceptional unwind releases its slot.
- [x] 5.3 Add permission regressions and split ambient parent validation from
  0700 normalization of rvw-owned slot directories.
- [x] 5.4 Add contended-cancellation regressions and replace blocking flock
  worker threads with cancellable nonblocking polling and capped jittered
  backoff.
- [x] 5.5 Add host-gate propagation regressions for adjudication, sampling,
  stack presence adjudication, and CLI-to-pipeline wiring.
- [x] 5.6 Synchronize main specifications and context, run all required bare
  verification gates plus change validation, and inspect the final diff for
  scope drift, including `uv.lock` and the external runtime registry.

## 6. Adversarial Review Remediation Round 3

- [x] 6.1 Synchronize the operation-modes delta, main specification, and
  rationale for cancellation-time runtime process-group termination and
  escalation logging; correct the slot-count identifier in the design.
- [x] 6.2 Extend the cancellation regression to prove graceful cleanup removes
  the wrapper and runtime child, and add a TERM-ignoring escalation regression
  that proves the whole tree exits and the run log records `SIGKILL`.
- [x] 6.3 Start runtime wrappers in dedicated sessions and terminate their
  process groups, falling back to direct signals when the process group can no
  longer be resolved.
- [x] 6.4 Run every requested bare verification gate and inspect the final diff
  for scope drift, including `uv.lock` and the external runtime registry.
