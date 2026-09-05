## Why

Reports currently hardcode `3` as the discovery agreement denominator even though discovery replicas are independently configurable and default to one. This makes ordinary findings, pattern folds, and publication payloads falsely describe the evidence collected by a run.

## What Changes

- Derive the displayed agreement denominator from persisted discovery coverage.
- Use the same denominator for ordinary report items, pattern-fold items, inline publication comments, and HTTP 422 body fallback items.
- Preserve `CollapseGroup.agreement` as the distinct discovery-replica numerator and preserve legacy rendering behavior when coverage is unavailable.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `reporting`: Report and publication finding renderers disclose the actual discovery replica denominator recorded by the run.

## Impact

Affected areas are deterministic report rendering, GitHub COMMENT payload construction, their persisted discovery-coverage input, and focused regression tests. Discovery dispatch, merge semantics, adjudication replicas, voting, and prompts are unchanged.
