## 1. Regression Tests

- [x] 1.1 Add failing signature and pipeline tests for independent validated discovery/adjudication counts and the three-replica adjudication default
- [x] 1.2 Add failing CLI review, gate, plan, auto, and stack boundary tests for split defaults and overrides
- [x] 1.3 Add a failing behavior test proving `--adjudicate-replicas 1` preserves single-vote adjudication

## 2. Implementation

- [x] 2.1 Split and validate the common pipeline parameters and update public adjudication defaults
- [x] 2.2 Add and forward independent CLI options across review, gate, auto, plan, and stack review without changing sample
- [x] 2.3 Extend plan and gate-plan payloads with `adjudicate_replicas` while keeping coverage and run totals based on discovery `replicas`

## 3. Specification and Verification

- [x] 3.1 Synchronize adjudication, discovery, operation-modes, and pr-gate main specs and contexts with the implemented split
- [x] 3.2 Run focused regression tests and all repository acceptance gates
