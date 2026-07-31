## 1. Regression contracts

- [x] 1.1 Add failing tests for merge-base member revisions and non-monotonic
  manifest order.
- [x] 1.2 Add failing tests for commit-pinned stack payloads and early run-ID
  recovery output.
- [x] 1.3 Add failing tests for duplicate presence IDs, batch-local IDs, and
  invalid-reason retry feedback.

## 2. Implementation

- [x] 2.1 Implement three-dot member diffs and manifest-relative lineage
  validation.
- [x] 2.2 Implement batch-local presence ID mapping, duplicate rejection, and
  retry feedback.
- [x] 2.3 Implement captured-tip `commit_id` publication and immediate stack
  run-ID output.

## 3. Specifications and verification

- [x] 3.1 Synchronize stack-review and reporting main specs and context.
- [x] 3.2 Run focused tests and inspect the complete diff.
- [x] 3.3 Run ruff check, ruff format check, ty, non-live pytest, and OpenSpec
  validation as bare commands.
- [x] 3.4 Archive the implemented change after every gate passes.
