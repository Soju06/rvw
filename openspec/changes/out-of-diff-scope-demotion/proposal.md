## Why

Agentic discovery can report technically valid defects in files the pull request did not change. The controller already owns the parsed three-dot hunks, so it can classify scope deterministically and prevent pre-existing findings from blocking an unrelated change. The measured consumer PR 2026-09-14 demonstrates the delay caused by treating those findings as actionable.

## What Changes

- Add controller-computed `scope`, `effective_severity`, and `demotion_reason` to enriched findings and collapse groups while preserving model-reported severity and the closed runtime severity enum.
- Classify findings as changed, unchanged_in_file, or outside_diff from parsed hunks and diff file membership; groups use the strongest member scope.
- Demote non-changed findings to informational effective severity for every gate, policy, report, synthesis, publication, and stack consumer. Keep them visible in a localized 참고 section and body-only publication with no inline threads.
- Add concise lane guidance to anchor defects caused by a change at the changed line that causes them.

## Capabilities

### Modified Capabilities

- `finding-model`
- `reporting`
- `pr-gate`
- `synthesis`
- `stack-review`
- `lane-registry`

## Impact

This is controller-side classification and presentation behavior. Runtime model output and wire severity remain unchanged; legacy artifacts without scope retain prior behavior by treating scope as changed when no diff evidence is available.
