## 1. Contract and regression tests

- [x] 1.1 Add a strict cloud-app-platform delta for supported text artifact
  transport and terminal process diagnostics.
- [x] 1.2 Add failing tests proving text artifact reads never request binary
  `none` encoding and missing-result summaries include filtered process facts.

## 2. Worker implementation

- [x] 2.1 Read persisted text artifacts explicitly as UTF-8 on the pinned SDK.
- [x] 2.2 Capture and best-effort persist terminal SDK logs, `process.json`, and
  the redacted environment snapshot before result parsing and cleanup.
- [x] 2.3 Include exit code, duration, and a secret-filtered stderr tail in
  missing-result Check Run summaries.
- [x] 2.4 Remove the redundant numeric-target repository lookup and install a
  versioned fallback auto policy while preserving base-revision precedence.

## 3. Documentation and verification

- [x] 3.1 Document the SDK transport contract, live measurements, verified
  invocation facts, and unresolved early-exit hypotheses.
- [x] 3.2 Run every required Python, OpenSpec, workflow, cloud, Wrangler, and
  Docker gate as a bare command and inspect the final diff for secrets.
- [x] 3.3 Commit, push `fix/cloud-artifact-transport`, and open a pull request
  to `main` without deploying.
