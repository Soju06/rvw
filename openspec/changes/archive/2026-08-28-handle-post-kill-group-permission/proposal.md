## Why

A real macOS cleanup verification showed that a zero-signal process-group probe
can raise `EPERM` immediately after RVW sends KILL. The child process was gone,
but the probe exception escaped cleanup and replaced the caller's intended
cancellation result.

## What Changes

- Treat an inaccessible post-KILL process group as unverified cleanup rather
  than an exception from the cancellation path.
- Write a stable run-log marker and return so the original cancellation or
  deadline classification can continue.

## Capabilities

### Modified Capabilities

- `runtime-contract`: Post-KILL process-group cleanup remains bounded when a
  captured group can no longer be probed because the operating system denies
  permission.

## Impact

The change is limited to the Codex runtime cleanup path, its deterministic
regression coverage, and the runtime-contract specification.
