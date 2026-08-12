## Context

Two cross-process concurrency defects were confirmed on 2026-08-12 while six
rvw processes shared one host:

1. `RunStore.create` builds `rvw-{YYYYmmdd-HHMMSS}-{kind}-{short}` and calls
   `mkdir(parents=True, exist_ok=False)`. Two runs on the same target within
   one second collide and the second crashes with `FileExistsError` before any
   artifact is written. `StackStore.create` already appends `-%f`, so the two
   stores are asymmetric.
2. `dispatch` retries an all-INVALID lane-chunk once, but the replacement wave
   recomputes the identical `lane_slug[/c{chunk}]/r{replica}` run directory.
   `CodexRuntime.execute_raw` then unlinks `out.json` and rewrites `prompt.md`,
   `schema.json`, and `run.log`, so the initial INVALID evidence is destroyed.
   `adjudicate` and `stack_adjudicate` already isolate retries with a
   `{label}-retry` directory.

## Goals / Non-Goals

- Goal: same-target concurrent run creation never fails on run-ID collision.
- Goal: initial-wave artifacts survive the replacement wave untouched.
- Non-goal: cross-process concurrency limiting (host-global semaphore); that
  needs its own design and an operator decision.
- Non-goal: changing run-ID validation (`_SAFE_RUN_ID`), stack stores, doctor
  selection, or artifact schemas.

## Decisions

### Run IDs carry microseconds and regenerate on residual collision

`RunStore.create` appends the `%f` microsecond field (matching
`StackStore.create`) and, if `mkdir` still raises `FileExistsError`, takes a
fresh timestamp and retries a bounded number of times before propagating the
error. Regeneration keeps the ID format identical (`_SAFE_RUN_ID`-safe,
timestamp-prefixed) so `RunStore.open`, gate inheritance, and doctor selection
are unaffected. A random suffix was rejected because the timestamp prefix is
the established sort/inspection convention and microsecond regeneration
already reduces the collision window to practical zero.

### Replacement waves write beneath a retry directory

The replacement wave's run directory becomes
`lane_slug[/c{chunk}]/retry/r{replica}`. The final path component must remain
`r{replica}` because `CodexRuntime.execute_raw` derives the replica number
from `run_dir.name` (`_REPLICA_DIRECTORY` fullmatch). A sibling-name scheme
such as `r{replica}-retry` would break that contract; a nested `retry/`
directory preserves it while keeping initial and retry artifacts separately
inspectable. Result identity, dedup keys, and reporting are unchanged: the
retry result still replaces the initial result per `(lane_id, replica, chunk)`.

## Risks / Trade-offs

- Open PR #15 rewrites much of `store.py`; the `create` edit is outside its
  hunks but a textual merge may still need attention. Accepted: both changes
  are small and semantically independent.
- Tools that assumed the retry overwrote the same directory would see two
  directories now; no such consumer exists in-repo (coverage and reports key
  on lane/replica/chunk, not paths).
