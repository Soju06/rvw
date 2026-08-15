## Why

Runtime deadlines are fixed at 600 seconds in six callable defaults and cannot be selected from the CLI, so an operator whose lane legitimately needs more than ten minutes can only observe a GNU `timeout` failure such as `exit_nonzero:124`. Earlier concurrency and replica changes explicitly deferred deadline behavior, leaving this operator control as a known gap.

## What Changes

- Define one shared 600-second runtime deadline default and a CLI ceiling of 1800 seconds.
- Add `--deadline` to `review`, `auto`, `gate`, `stack review`, and `sample`, preserving the 600-second default and rejecting values outside 1 through 1800 before runtime work.
- Thread the selected base deadline through every discovery, adjudication, sampling, and stack-presence runtime path while preserving the existing doubled deadline for expanded adjudication passes.
- Add deterministic regressions for callable defaults, command-path propagation, CLI bounds, and the expanded-pass multiplier.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: Define the default deadline used by bounded runtime dispatch and preserve explicit positive deadline values.
- `operation-modes`: Require runtime-executing commands to expose, bound, and propagate a `--deadline` option.

## Impact

Affected implementation includes `src/rvw/dispatch.py`, discovery, adjudication, sampling, stack presence adjudication, shared pipeline plumbing, and Typer CLI command handlers. Tests and the discovery and operation-modes specifications change; the external runtime registry, persisted run and report schemas, model selection, version, lockfile, and dependencies do not.
