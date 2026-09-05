## Context

See [proposal.md](proposal.md) for motivation. `discover.json` already persists strict per-lane run coverage whose entries identify every planned `(replica, chunk)` pair. Report rendering receives that coverage, while publication currently rerenders some finding items without receiving it.

## Goals / Non-Goals

**Goals:**

- Use one discovery-derived denominator consistently across report and publication renderers.
- Preserve old persisted artifacts and direct renderer callers that have no coverage.
- Keep the contract small enough to avoid a new persisted configuration field.

**Non-Goals:**

- Changing the `CollapseGroup.agreement` numerator.
- Changing discovery dispatch, adjudication votes, prompts, thresholds, or policy evaluation.
- Refactoring the existing report module.

## Decisions

### Derive the count from exact persisted coverage

The renderer will take the maximum planned replica identifier across coverage run entries. Each lane records the exact planned replica/chunk identity set, so this recovers the configured count even when a replica is invalid or reports no findings. Summing dispatched or valid counts was rejected because chunks multiply dispatches and invalid executions still belong in the configured denominator.

### Preserve a legacy fallback only when coverage is unavailable

Coverage-free direct calls and historical artifacts will retain the previous denominator of three. Inferring the denominator from group agreement was rejected because low agreement under a multi-replica run would understate the configured evidence opportunity.

### Pass coverage into publication

Publication will receive the persisted lane coverage already loaded by each caller and use the shared derivation for every group-item rendering path. Parsing the Markdown report was rejected because inline and fallback items are generated from typed merge artifacts and must not depend on prose structure.

## Risks / Trade-offs

- [Historical artifacts without exact run coverage continue to display `/3`] → Preserve compatibility instead of inventing a count; current strict artifacts always carry run entries.
- [Chunked discovery could inflate a naive denominator] → Derive from replica identifiers, not dispatched totals.
- [A publication caller omits coverage] → Keep the parameter backward-safe but update and test every repository production caller.

## Migration Plan

No artifact migration is required. Re-rendering a current run reads `discover.json`; reverting restores the old display-only denominator without changing stored findings or merge results.
