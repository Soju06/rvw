## Why

Concurrent rvw processes can collectively exceed the backing LLM gateway's per-account capacity, causing overload retries and INVALID lane results. Runtime execution therefore needs a safer default and an explicit operator control.

## What Changes

- Lower every runtime execution semaphore default from 16 to 8.
- Add a positive `--concurrency` option, defaulting to 8, to CLI commands that execute model runtime work.
- Thread the selected concurrency through ordinary review, sampling, stacked review, adjudication, and stack presence adjudication without changing replica semantics.
- Add deterministic regressions for the callable default, CLI plumbing, and rejection of zero concurrency.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: Lower the bounded dispatch default to eight and preserve explicit positive concurrency overrides.
- `operation-modes`: Require runtime-executing CLI commands to expose and propagate a positive `--concurrency` option with a default of eight.

## Impact

Affected implementation includes `src/rvw/dispatch.py`, discovery, adjudication, sampling, stack presence adjudication, shared pipeline plumbing, and Typer CLI command handlers. Tests and the discovery and operation-modes specifications change; the external runtime registry, report schemas, model selection, version, and dependencies do not.
