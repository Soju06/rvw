## 1. Regression Coverage

- [x] 1.1 Add a deterministic regression proving cleanup returns when the
  post-KILL process-group probe does not clear.

## 2. Bounded Cleanup

- [x] 2.1 Bound the post-KILL process-group wait and record persistent cleanup.
- [x] 2.2 Prevent the process-owner wait task from remaining pending on the
  persistent-group path.

## 3. Specification and Verification

- [x] 3.1 Synchronize the runtime-contract main spec and context.
- [x] 3.2 Run focused runtime tests, required bare gates, and OpenSpec
  validation.
