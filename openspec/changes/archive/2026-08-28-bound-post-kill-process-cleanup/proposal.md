## Why

The adapter correctly escalates a runtime process group from TERM to KILL, but
then waits indefinitely for the process-group probe to disappear. A completed
runtime can therefore leave its RVW parent blocked in cleanup even though no
new review work can start.

## What Changes

- Bound the process-group exit wait after SIGKILL to the existing five-second
  cleanup interval.
- Record a persistent-process-group cleanup marker when that final wait expires
  and let the original cancellation or deadline classification continue.

## Capabilities

### Modified Capabilities

- `runtime-contract`: Process cleanup remains best-effort and bounded even when
  the post-KILL process-group probe never clears.

## Impact

The change is limited to the Codex runtime cleanup path, its deterministic
regression coverage, and the runtime-contract specification.
