---
lane: correctness
tier: base
schedule_hint: heavy
covered_by_others: inject
severity_cap: blocker
validation: pending
---

# correctness

One question: does this change break anything real? Severe defects first,
then the contextual edge cases this specific change makes dangerous, then a
safety-net sweep for serious defects no other active lane covers.

`bug/severe-defect` — report only defects with real production impact:

- logic inversion, off-by-one, wrong operator on a hot path
- unhandled error that crashes or corrupts state (not merely logs ugly)
- race condition / lost update on shared state
- resource leak (connections, file handles, subscriptions) on a repeated path
- data loss or silent data corruption (failure returned as success, partial
  write treated as complete)
- boundary values (empty, null, zero, max) that take a broken path

Report the concrete failure sequence: input → path → wrong outcome. A bug you
cannot walk through step-by-step in the code is a hypothesis — do not report
hypotheses.

Given what this change is FOR (see the review brief when present), find the
edge cases and side effects its context makes dangerous:

- `dynamic/unhandled-edge` — inputs/states plausible in this change's real
  usage context that take a broken path: empty/huge collections, concurrent
  invocation, retry/replay, partial failure of a multi-step operation,
  boundary values of newly introduced parameters.
- `dynamic/unintended-side-effect` — the change alters behavior of flows
  outside its declared purpose: shared state mutated, event ordering changed,
  caching now serving stale data to an unrelated reader, performance cliffs
  on existing paths.

Ground every finding in the specific purpose and context of THIS change; do
not enumerate generic edge-case checklists.

Safety-net sweep (ADR-005): find SERIOUS defects that the other active lanes
structurally miss. The other active lanes' rule lists are injected below as
"already covered" — do NOT re-report anything in those classes.

- `unscoped/security` — exposure not covered by the security lane's rules.
- `unscoped/correctness` — real functional defects: error handling that hides
  failure as success, cache identity/invalidation bugs, state machines that
  can wedge.
- `unscoped/contract` — public inputs silently dropped instead of reaching
  the downstream call; response shapes that lie about what happened.
- `unscoped/scope-creep` — behavior in the diff that plainly does not belong
  to any declared purpose visible in the code.

Report `unscoped/*` findings at warning severity at most: they surface
candidates for adjudication; they do not block on their own.

## rule: bug/severe-defect

The rule is defined by the lane guidance above.

## rule: unscoped/security

The rule is defined by the lane guidance above.

## rule: unscoped/correctness

The rule is defined by the lane guidance above.

## rule: unscoped/contract

The rule is defined by the lane guidance above.

## rule: unscoped/scope-creep

The rule is defined by the lane guidance above.

## rule: dynamic/unhandled-edge

The rule is defined by the lane guidance above.

## rule: dynamic/unintended-side-effect

The rule is defined by the lane guidance above.
