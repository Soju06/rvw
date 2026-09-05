---
lane: test-integrity
tier: scope
schedule_hint: normal
severity_cap: blocker
validation: pending
when:
  paths:
  - '**/test*/**'
  - 'test*/**'
  - '**/__tests__/**'
  - '__tests__/**'
  - '**/test_*.py'
  - 'test_*.py'
  - '**/*.test.*'
  - '*.test.*'
  - '**/*.spec.*'
  - '*.spec.*'
  - '**/*_test.*'
  - '*_test.*'
---

# test-integrity

Review whether changed tests can detect the behavior they claim to check.
Report serious false assurance in existing tests, not a demand for new test files.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: test-ci/critical-flaw

A test must fail when the behavior it claims to protect is broken. Tautologies, mocking
the unit under test, swallowed assertion failures and assertions on unrelated behavior
create false assurance. Trace setup, execution and assertions and demonstrate a concrete
broken implementation that still passes. Only report changed test logic with material
consequences.
