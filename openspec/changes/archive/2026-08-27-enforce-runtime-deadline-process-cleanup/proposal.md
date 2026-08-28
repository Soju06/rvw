## Why

The external foreground `timeout` wrapper can reach its deadline while a Codex
process tree remains alive, leaving RVW host slots and review work running past
the selected bound. RVW already owns a process-group cleanup path for task
cancellation, so deadline expiry must use that path as well.

## What Changes

- Enforce each selected runtime deadline inside the Codex adapter rather than
  delegating it to an external `timeout` process.
- On expiry, cancel the adapter-owned subprocess task so its process group is
  terminated with the existing bounded TERM-to-KILL cleanup path.
- Preserve the machine-readable timeout outcome as `exit_nonzero:124` and
  continue to write invalid usage artifacts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtime-contract`: Make RVW, rather than an external timeout wrapper, own
  deadline enforcement and full runtime process-tree cleanup.

## Impact

The Codex runtime command construction and deadline handling change in
`src/rvw/runtimes/codex.py`, with deterministic runtime-adapter regressions.
No CLI surface, registry, persisted schema, dependency, or default deadline
value changes.
