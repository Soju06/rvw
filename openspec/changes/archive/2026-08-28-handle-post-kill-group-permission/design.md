## Goals

- Preserve the existing TERM grace period and KILL escalation.
- Preserve the original cancellation or deadline result when a post-KILL probe
  receives `EPERM`.
- Leave evidence in `run.log` when cleanup cannot be verified.

## Design

After RVW sends KILL, cleanup catches `EPERM` from the process-group exit
probe and treats it as unverified cleanup rather than an unwind failure. It
records a stable marker, cancels any remaining leader wait task, and returns to
the original unwind path. RVW does not signal the inaccessible group again,
because `EPERM` does not prove that the captured group is still owned by the
runtime.

## Non-goals

- Changing deadlines, timeout classification, or signal ordering.
- Claiming that an unverified group is successfully reaped.
- Retrying review work or modifying the external lane registry.
