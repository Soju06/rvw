## Context

`execute_raw` currently prepends GNU `timeout --foreground` to every Codex
invocation. A live review showed that this wrapper can exceed its configured
deadline while its Codex descendants remain alive. Separately, `_spawn`
already starts a new session and, when cancelled, terminates its entire process
group with TERM, waits five seconds, then escalates to KILL. See `proposal.md`
for the operational motivation.

## Goals / Non-Goals

**Goals:**

- Make the adapter's selected deadline cancel the task that owns the spawned
  process group.
- Reuse the established cleanup and persisted-invalid-result behavior.
- Preserve compatibility for callers that recognize a deadline as
  `exit_nonzero:124`.

**Non-Goals:**

- Change the selected deadline value, CLI bounds, policy, concurrency, or
  retry behavior.
- Alter cancellation initiated by a caller, parent-death coupling, or the
  process-group grace duration.
- Add platform-specific timeout binaries or dependencies.

## Decisions

### Own deadline cancellation in the adapter

Wrap `_spawn(...)` in `asyncio.wait_for` using the selected deadline. On expiry,
`wait_for` cancels `_spawn`; `_spawn` then runs its existing shielded cleanup,
which signals the process group and reaps it before timeout handling returns.
The previous external-wrapper approach is rejected because it assigns deadline
and process-tree ownership to different processes.

### Preserve the timeout result wire contract

Catch the adapter timeout separately and return the same invalid result that an
external timeout exit code produced: `exit_nonzero:124`. This avoids changing
dispatcher retry classification, reports, and any artifact readers. Ordinary
caller cancellation remains a propagated `CancelledError` with canceled usage.

### Keep the existing termination grace

Deadline expiry reuses the five-second TERM-to-KILL cleanup already used by
caller cancellation. Replacing it with the old wrapper's thirty-second grace
would duplicate termination policy and retain a longer unbounded process-tree
window.

## Risks / Trade-offs

- [A timeout result returns after bounded cleanup, rather than exactly at the
  selected second] → The process tree is no longer left alive; the existing
  five-second escalation caps the additional wait.
- [A cancellation race could be mistaken for deadline expiry] → Catch only
  `TimeoutError`; a direct `CancelledError` retains its current usage and
  propagation contract.
- [Mock-only coverage could miss cleanup integration] → Keep the existing
  Linux process-tree cancellation regressions and add an adapter-deadline test
  that proves the spawned task is cancelled and records exit code 124.

## Migration Plan

Ship with no persisted-schema migration. Rollback restores the external timeout
prefix; completed and invalid artifacts remain readable because the timeout
reason stays `exit_nonzero:124`.
