## 1. Planner Contract and TDD

- [x] 1.1 Replace the aggregate-overage regression with failing one-chunk byte-preservation and synthetic 735K ordered multi-chunk tests
- [x] 1.2 Implement strict `DiffChunk` and placement report models plus order-preserving next-fit packing, and remove `DiffBudgetExceeded`
- [x] 1.3 Update budget persistence and report tests for chunk count and placement accounting

## 2. Discovery Fanout and Identity

- [x] 2.1 Add failing tests for chunk prompt metadata, complete file assignment, multi-chunk artifact paths, and one-chunk path compatibility
- [x] 2.2 Extend planned/results dispatch identity, retry, deduplication, and sorting over the chunk axis
- [x] 2.3 Fan discovery out over lane, replica, and chunk while preserving full-diff hunk enrichment
- [x] 2.4 Add a regression proving stable merge finding IDs are unchanged by chunk placement

## 3. Exact Coverage and Gate

- [x] 3.1 Add failing strict coverage-ledger tests, including one invalid or missing chunk causing gate failure
- [x] 3.2 Persist exact per-lane replica-chunk records with aggregate consistency validation
- [x] 3.3 Add chunk count to gate plans and validate the exact lane-replica-chunk Cartesian product
- [x] 3.4 Update gate verdict, report, doctor, CLI totals, and fixture-backed persistence consumers

## 4. Sample and Plan

- [x] 4.1 Add failing tests proving large sampling fixtures use every enum/free-replica-chunk combination and preserve one-chunk paths
- [x] 4.2 Route sampling through the shared planner and expose its chunk count
- [x] 4.3 Add failing CLI plan tests for chunk count and lane x replica x chunk total runs
- [x] 4.4 Route CLI plan and gate-plan construction through the shared planner and render chunk totals

## 5. Specification Sync and Verification

- [x] 5.1 Synchronize discovery, lane-registry, runtime-contract, operation-modes, pr-gate, and reporting main specs and context evidence
- [x] 5.2 Run focused regression tests and fix strict-schema or compatibility fallout
- [x] 5.3 Run ruff check, ruff format check, ty, non-live pytest, and OpenSpec validation as bare commands
