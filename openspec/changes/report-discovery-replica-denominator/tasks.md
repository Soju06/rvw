## 1. Report rendering

- [x] 1.1 Add an ordinary-item regression test for a non-default discovery count, capture the current `/3` failure, and make it pass by deriving the denominator from exact persisted coverage.
- [x] 1.2 Add a pattern-fold regression test for a non-default discovery count and verify the fold uses the same discovery-derived denominator.

## 2. Publication rendering

- [x] 2.1 Pass persisted discovery coverage through every ordinary publication caller and verify inline plus HTTP 422 fallback items never restore `/3` for a one-replica run.

## 3. Specification and verification

- [x] 3.1 Synchronize the main reporting spec and context with the implemented compatibility contract and validate OpenSpec.
- [x] 3.2 Run focused regression tests, all repository verification gates, `git diff --check`, the Python LOC/strict-rule audit, and a manual dry-run CLI report/publish scenario.
