## 1. OpenSpec and contracts

- [x] 1.1 Add scope/effective-severity fields to enriched and collapsed models without changing runtime output schemas.
- [x] 1.2 Define deterministic hunk/file classification and strongest-group scope, including legacy artifact fallback.
- [x] 1.3 Update finding-model, reporting, pr-gate, synthesis, stack-review, and lane-registry specs and contexts.

## 2. Behavioral implementation

- [x] 2.1 Compute scope and demotion in discovery/merge from controller hunks.
- [x] 2.2 Make every gate, policy, report, synthesis, publication, and stack consumer use effective severity.
- [x] 2.3 Render demoted findings in localized 참고 body sections, exclude them from action counts/events/threads, and add lane prompt guidance.

## 3. Verification

- [x] 3.1 Add deterministic regression fixtures covering changed, unchanged_in_file, outside_diff, group precedence, gates, report, publish, and synthesis.
- [x] 3.2 Run parity checks for every modified capability and the complete validation gates.
- [x] 3.3 Record implementation and gate results in `/tmp/rvw-scope-report.md`; do not archive this change.
