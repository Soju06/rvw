## Goals

- Preserve TERM, the existing five-second grace period, and KILL escalation.
- Ensure cancellation and deadline handling cannot remain blocked after KILL.
- Keep the evidence in `run.log` when cleanup remains observable after KILL.

## Design

Reuse `_PROCESS_TERMINATION_TIMEOUT_SECONDS` for both group-exit waits. After
the initial TERM grace expires, send SIGKILL and wait for the captured group for
at most one further cleanup interval. If that wait times out, append a stable
marker to the run log and continue the original cancellation path. The process
owner is still awaited normally when the group has disappeared; the persistent
group branch cancels its owner wait task so it cannot leave a pending asyncio
task behind.

## Non-goals

- Changing deadline duration or timeout classification.
- Retrying review work or editing the external lane registry.
- Treating a best-effort persistent-group marker as a successful cleanup.
