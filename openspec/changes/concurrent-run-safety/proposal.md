## Why

Concurrent rvw runs against the same target crash at startup: ordinary run IDs
use a second-resolution timestamp plus target identity, and `RunStore.create`
calls `mkdir(exist_ok=False)`, so two runs starting within the same second
raise `FileExistsError` (reproduced 2026-08-12). Stack runs already carry a
microsecond component, so only the ordinary store is exposed.

Separately, the dispatcher's all-invalid replacement wave reuses the exact
initial run directories. The runtime adapter unlinks `out.json` and rewrites
`prompt.md` and `run.log`, destroying the initial INVALID evidence needed for
post-hoc failure triage. Adjudication already separates retry artifacts with a
`-retry` label; dispatch does not.

## What Changes

- Ordinary run IDs gain a sub-second component, and residual run-directory
  name collisions are resolved by regenerating the identifier instead of
  failing.
- Dispatch replacement waves persist artifacts in a directory distinct from
  the initial wave so INVALID evidence survives the retry.
- Add deterministic regressions for same-second same-target creation and for
  initial-artifact preservation across a retry.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `reporting`: Run-directory creation is collision-free under concurrent
  same-target runs.
- `discovery`: The all-invalid replacement wave preserves the initial wave's
  artifacts.

## Impact

Affected implementation is `src/rvw/store.py` (`RunStore.create`) and
`src/rvw/dispatch.py` (replacement-wave run directories), plus their tests and
the reporting and discovery specifications. Run-ID validation, stack stores,
report schemas, publication, model selection, version, and dependencies do not
change.
