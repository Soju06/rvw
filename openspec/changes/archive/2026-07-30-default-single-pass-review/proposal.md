## Why

Owner decision (2026-07-30): rvw's ordinary purpose is a single-pass scan, not a multi-replica "panel of judges." Replication remains useful for high-stakes or large-scope reviews, but making it the default multiplies lanes, replicas, and concurrent rvw instances until the `codex-lb` executor is overloaded; four concurrent runs were observed demanding up to 64 sessions.

## What Changes

- Default `rvw review`, `rvw gate`, and `rvw auto` execution and plan payloads to one replica.
- Default direct discovery and adjudication calls to one replica.
- Preserve `--replicas N` for `N >= 2` as the unchanged opt-in heavy-verification mode.
- Keep sampling defaults, concurrency and deadline controls, retry and widening behavior, and majority-vote implementation unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `operation-modes`: Define one replica as the default for review and auto while preserving explicit replication.
- `discovery`: Change the default lane-and-chunk dispatch count from three replicas to one.
- `adjudication`: Change the default verdict pass from three replicas to one while retaining strict-majority voting.
- `pr-gate`: Define one replica as the default for a target-mode gate review while preserving explicit replication.

## Impact

The change affects CLI option and plan defaults in `src/rvw/cli.py`, callable defaults in `src/rvw/discover.py` and `src/rvw/adjudicate.py`, their regression tests, the four modified capability specs and contexts, and README statements about the normal replica count. It does not change the external lane registry, runtime concurrency, retry or widening passes, majority-vote logic, or the statistical sampling tool.
