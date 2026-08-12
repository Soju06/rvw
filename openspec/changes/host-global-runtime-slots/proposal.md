## Why

The `--concurrency` semaphore is process-local: every rvw process creates its
own `asyncio.Semaphore(8)`, so N concurrent rvw processes admit up to N x 8
runtime executions against the shared backing gateway. On 2026-08-06 this
saturated the gateway's per-account stream capacity (account pool exhaustion,
30-second selection retry sleeps, lane INVALIDs from 503 degraded mode), and
the per-process default lowered in #13 does not bound the host total: six
concurrent processes were observed on 2026-08-12 with a theoretical 48-stream
fan-out. The real constraint is host-global, so the limiter must be too.

## What Changes

- Runtime executions additionally acquire a host-global slot from a
  file-lock-based (flock) slot directory shared by every rvw process on the
  host, released when the execution finishes.
- The host-global cap defaults to 12 and is configurable via
  `RVW_HOST_CONCURRENCY` (positive integer; invalid values are rejected at
  startup). Setting `RVW_HOST_CONCURRENCY=0` disables the host-global gate.
- The per-process `--concurrency` option keeps its existing meaning and
  default; the effective in-flight bound is the minimum of both gates.
- Add deterministic regressions for slot exhaustion blocking, release on
  completion and on failure, cross-instance sharing, disablement, and
  invalid-value rejection.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: Dispatch bounds in-flight runtime executions by the
  host-global slot gate in addition to the per-process semaphore.
- `operation-modes`: Runtime-executing commands honor the
  `RVW_HOST_CONCURRENCY` contract.

## Impact

Affected implementation is a new slot-gate module plus acquisition around
runtime execution in `src/rvw/dispatch.py`, `src/rvw/adjudicate.py`,
`src/rvw/sample.py`, and `src/rvw/stack_adjudicate.py`, with tests and the
discovery and operation-modes specifications. Replica semantics, CLI options,
report schemas, and dependencies do not change.
