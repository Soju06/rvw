## 1. Regression Tests

- [x] 1.1 Add failing auto-discovery tests that select the newest qualifying same-repo/PR disposition run among newer decoys
- [x] 1.2 Add failing CLI tests for `--no-inherit`, explicit-source precedence, no-source fail-open messaging, and conflicting flags

## 2. Implementation

- [x] 2.1 Implement best-effort prior-run discovery with current-run, target-type, repository, PR, completion, disposition, and timestamp qualification
- [x] 2.2 Integrate the selected run ID into the existing inheritance load/match/summary/provenance path and expose selection or absence in output
- [x] 2.3 Add `--no-inherit`, enforce option precedence and conflict validation, and keep resume mode free of automatic discovery

## 3. Specification and Verification

- [x] 3.1 Synchronize the pr-gate main spec and context with automatic inheritance behavior
- [x] 3.2 Run focused regression tests and all repository acceptance gates
