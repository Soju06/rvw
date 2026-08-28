## 1. Regression Coverage

- [x] 1.1 Add a deterministic regression for `EPERM` from the post-KILL group
  probe.

## 2. Bounded Cleanup

- [x] 2.1 Treat an inaccessible post-KILL group as unverified cleanup and
  continue the original unwind path.
- [x] 2.2 Record a stable run-log marker and prevent a pending leader wait.

## 3. Specification and Verification

- [x] 3.1 Synchronize the runtime-contract main spec and context.
- [x] 3.2 Run focused runtime tests, a real cleanup exercise, required bare
  gates, and OpenSpec validation.
