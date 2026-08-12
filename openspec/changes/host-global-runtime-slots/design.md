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
- Non-goal: cross-host coordination, gateway-side queueing, or fairness/aging
  between processes.
- Non-goal: bounding non-runtime work (git, gh, parsing).
- Follow-up: thresholded host-slot wait/contention events are deferred; this
  change does not add wait observability.

## Decisions

### flock slot directory, kernel-released on death

The gate's slot count comes from `RVW_HOST_CONCURRENCY` and is stored as
`HostSlotGate.cap`. Its lock files (`slot-00` through `slot-{cap-1}`) live
under `$XDG_RUNTIME_DIR/rvw-slots/c{cap}/` when `XDG_RUNTIME_DIR` is set, else
`/tmp/rvw-slots/c{cap}/`, so mixed-cap processes never deadlock on mismatched
slot counts. Acquisition tries each slot file with
`flock(LOCK_EX | LOCK_NB)` in random start order. If none is free, the async
caller sleeps with modest jitter and capped backoff before rescanning every
slot. `flock` locks are released by the kernel when
the descriptor closes, including on SIGKILL, so no stale-slot cleanup or pid
bookkeeping is needed. Directory and files are created lazily with 0700 and
`O_NOFOLLOW`; `/tmp/rvw-slots` pre-existing as a symlink or wrong-owner
directory fails closed with a clear error.

The ambient `$XDG_RUNTIME_DIR` is validated by descriptor without changing its
mode or rejecting group and other permission bits because rvw does not own its
permission contract. Existing owner-matched rvw-owned directories
(`rvw-slots` and `c{cap}`) are normalized to 0700 and verified through their
opened descriptors. A validated slot-directory descriptor stays open
throughout each nonblocking scan, and candidate files are opened relative to
it so the path is not re-resolved after validation. `O_NOFOLLOW` is mandatory
rather than optional: platforms without it fail gate construction.

On Linux, the spawned command is prefixed with
`setpriv --pdeathsig SIGTERM`, applying `PR_SET_PDEATHSIG(SIGTERM)` exec-side
without Python `preexec_fn` work in the multithreaded process. GNU timeout then
receives the parent-death `SIGTERM`, forwards it to codex, and exits. Linux
execution fails closed with a clear error if `setpriv` is unavailable. This
closes the ordinary gap in which SIGKILL releases rvw's flock while its runtime
child continues using a gateway stream. Unlike the former pre-exec parent-PID
recheck, an rvw death in the tiny window before `setpriv` runs can leave the
child orphaned; that race is accepted to eliminate thread-unsafe post-fork
Python execution. The former generic subprocess-error concern for swallowed
`preexec_fn` errno is also eliminated because there is no `preexec_fn` path.
The coupling is Linux-only; other platforms retain normal subprocess lifetime
semantics.

### Acquisition wraps the runtime execution, inside the local semaphore

Each `execute_one` acquires the process-local semaphore first, then the
host slot immediately around `runtime.execute*` (the expensive stream), and
releases both on completion or exception (`finally`). Ordering local-first
keeps a process's queued work from hoarding host slots while waiting on its
own semaphore. Contention uses short nonblocking scans on the event loop
followed by async sleeps with 0.05-second initial delay, modest jitter, and
backoff capped at 0.25 seconds. Cancellation therefore occurs with no
descriptor held and no blocking executor thread stranded. Polling does not
provide kernel FIFO fairness, which is acceptable for caps of at most dozens
and sub-second scans.

Each runtime wrapper leads a dedicated process group. Once a runtime subprocess
starts, cancellation or any other exceptional unwind sends `SIGTERM` to that
group and reaps the wrapper before the host-slot context can exit. Cleanup waits
up to five seconds, then sends `SIGKILL` to the group, appends an escalation
marker to the run log, and waits again. Group signaling prevents a killed
timeout wrapper from orphaning its codex descendant while the rvw parent remains
alive and the host slot is released.

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
- Cap values intentionally select disjoint `c{cap}` lock pools. Processes
  configured with different caps therefore do not share one host bound, which
  prevents cross-cap deadlock but means changing `RVW_HOST_CONCURRENCY`
  mid-fleet temporarily creates disjoint pools until configurations converge.
- Polling sacrifices kernel FIFO fairness and can add up to the capped polling
  interval before a freed slot is noticed. At the intended cap sizes, bounded
  cancellation and rescanning every slot outweigh that trade-off.
- A process holding a slot through a hung stream delays others; the runtime
  deadline (`timeout --kill-after`) already bounds this.
- Tests must not depend on wall-clock timing; regressions use small caps and
  deterministic acquire/release sequencing via events.
