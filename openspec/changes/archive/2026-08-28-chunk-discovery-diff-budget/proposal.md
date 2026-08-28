## Why

The aggregate diff limit currently aborts otherwise legitimate reviews after generated and oversized files have already been excluded. Measured 464K and 735K source diffs show that the limit must become a per-prompt quality budget while exact coverage remains fail-closed.

## What Changes

- **BREAKING** Replace `apply_diff_budget()`'s single filtered-diff return and `DiffBudgetExceeded` failure with ordered file-group chunks plus chunk placement accounting; remove `DiffBudgetExceeded` without an alias.
- Fan discovery out across lane, replica, and chunk, with cross-chunk file metadata in every chunk prompt.
- Add chunk-aware artifact paths for multi-chunk runs while preserving the existing one-chunk paths byte-for-byte.
- Record and validate coverage for every planned lane-replica-chunk combination so any missing or invalid chunk blocks the PR gate.
- Reuse the same chunk planner for sampling fixtures and expose chunk and total-run counts in `rvw plan`.
- Preserve merge identity as `(file, hunk_id, rule_id)`, independent of chunk placement.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: Replace aggregate rejection with ordered chunk planning, chunk prompts, three-axis fanout, and exact run-level coverage.
- `lane-registry`: Define review planning and plan output over lane, replica, and chunk axes.
- `runtime-contract`: Define backward-compatible single-chunk and explicit multi-chunk artifact directories.
- `operation-modes`: Route sampling fixtures through the shared chunk planner and execute both variants per chunk.
- `pr-gate`: Persist the chunk count in the gate plan and validate every planned lane-replica-chunk result exactly.
- `reporting`: Describe coverage totals as chunk-expanded runs and include chunk budget accounting.

## Impact

Affected modules include `diffbudget`, discovery/dispatch, sampling, CLI planning, runtime artifact handling, gate models and validation, persisted discovery/budget schemas, reports, and their tests. Existing one-chunk review artifact paths and prompt diff bytes remain unchanged; persisted strict schemas gain explicit chunk planning and coverage fields. The external review registry is unaffected.
