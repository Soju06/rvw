## 1. Regression Tests

- [x] 1.1 Add failing dispatch tests proving only schema/format all-invalid
  groups retry and timeout-shaped groups do not.
- [x] 1.2 Add failing discovery tests proving zero-valid lane/chunk work fails
  closed after the permitted retry decision.
- [x] 1.3 Add failing lane/discovery/plan tests for scope defaults, explicit
  metadata, and `requires_brief` skipped coverage.

## 2. Implementation

- [x] 2.1 Classify retry reasons at the dispatcher and expose non-retried
  incomplete lane/chunk groups.
- [x] 2.2 Fail discovery closed with its persisted evidence intact on
  incomplete coverage.
- [x] 2.3 Add strict compatible lane and coverage metadata, including plan
  output for declarative scope and explicit brief-unavailable skip.
- [x] 2.4 Persist the exact discovery plan and each completed attempt, then
  expose `rvw run --run <id>` to resume only that plan.

## 3. Specification and Verification

- [x] 3.1 Synchronize discovery, lane-registry, and operation-mode specs and
  contexts without changing the external registry.
- [x] 3.2 Run focused tests, required bare gates, and OpenSpec validation.
