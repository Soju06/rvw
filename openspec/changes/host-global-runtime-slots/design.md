## Context

Two limiter layers exist today: the gateway's own admission control
(codex-lb rejects with local `account_stream_cap`-class errors but does not
queue) and rvw's per-process semaphore. Nothing bounds the host total, and
the codex CLI retries rejected streams with 30-second sleeps, so overshoot
degrades every concurrent run. A host-global gate on the client side queues
instead of burning retry sleeps.

## Goals / Non-Goals

- Goal: bound total in-flight runtime executions across all rvw processes on
  one host, cooperatively, with zero new dependencies.
- Goal: crash-safe release — a killed process must free its slots.
- Non-goal: cross-host coordination, gateway-side queueing, fairness/aging
  between processes (kernel flock wakeup order is acceptable).
- Non-goal: bounding non-runtime work (git, gh, parsing).

## Decisions

### flock slot directory, kernel-released on death

The gate is a directory of `_RVW_HOST_SLOT_COUNT` lock files (`slot-00` ..)
under `$XDG_RUNTIME_DIR/rvw-slots/` when set, else `/tmp/rvw-slots/`,
sharded by cap value (`.../c{cap}/`) so mixed-cap processes never deadlock on
mismatched slot counts. Acquisition tries each slot file with
`flock(LOCK_EX | LOCK_NB)` in random start order; if none is free it blocks
on one with plain `LOCK_EX`. `flock` locks are released by the kernel when
the descriptor closes, including on SIGKILL, so no stale-slot cleanup or pid
bookkeeping is needed. Directory and files are created lazily with 0700 and
`O_NOFOLLOW`; `/tmp/rvw-slots` pre-existing as a symlink or wrong-owner
directory fails closed with a clear error.

### Acquisition wraps the runtime execution, inside the local semaphore

Each `execute_one` acquires the process-local semaphore first, then the
host slot immediately around `runtime.execute*` (the expensive stream), and
releases both on completion or exception (`finally`). Ordering local-first
keeps a process's queued work from hoarding host slots while waiting on its
own semaphore. Blocking flock calls run in `asyncio.to_thread`, keeping the
event loop free; on cancellation the thread's descriptor is closed, which
releases the lock.

### One env knob, min-of-gates semantics

`RVW_HOST_CONCURRENCY` (default 12) sets the host cap; `0` disables the gate
entirely (single-tenant hosts, CI). Non-integer or negative values fail
closed at command startup with a usage error rather than being silently
ignored. `--concurrency` is untouched: the effective bound is
`min(per-process, host)`. Default 12 sits above one process's default 8 (no
behavior change for the single-process case) and below the 2026-08-06
observed overload region (16+ concurrent streams), and stays operator-tunable
per host.

## Risks / Trade-offs

- Blocking waits add queueing latency under host contention; that replaces
  gateway 503/retry-sleep degradation, which is strictly worse.
- flock on NFS is unreliable, but the slot root is host-local tmpfs/tmp by
  construction.
- A process holding a slot through a hung stream delays others; the runtime
  deadline (`timeout --kill-after`) already bounds this.
- Tests must not depend on wall-clock timing; regressions use small caps and
  deterministic acquire/release sequencing via events.
