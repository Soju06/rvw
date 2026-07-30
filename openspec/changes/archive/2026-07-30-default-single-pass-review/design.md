## Context

The CLI currently has two declared production defaults: `_PLAN_REPLICAS = 3`, which feeds `rvw plan`, target-mode `rvw gate`, and `rvw auto`, and a separate `review --replicas` default of three. The public `discover` and `adjudicate` callables also default to three. Replication multiplies lane and chunk work and can compound across concurrent rvw processes; four concurrent runs were observed requesting as many as 64 `codex-lb` sessions.

The owner decision on 2026-07-30 defines ordinary rvw use as a single-pass scan. Multi-replica review remains an explicit heavy-verification mode for high-stakes or large-scope work.

## Goals / Non-Goals

**Goals:**

- Make every declared production review default one replica.
- Keep explicit replica counts, including `N >= 2`, behaviorally unchanged.
- Keep CLI plan output and execution defaults aligned.
- Lock the default contract with CLI and callable-signature regression tests.

**Non-Goals:**

- Change `sample.py`, whose lane-validation purpose remains statistical.
- Change dispatch or adjudication semaphores, deadlines, retry waves, widening passes, or majority-vote implementation.
- Change the external lane registry.
- Refactor the replica plumbing or incidental code.

## Decisions

1. Change only the declared defaults. `_PLAN_REPLICAS` becomes one, the independent `review --replicas` default becomes one, and the `discover` and `adjudicate` parameter defaults become one. Existing option validation and propagation remain untouched. This is smaller and safer than introducing a configuration layer for a fixed owner policy.

2. Preserve strict-majority voting exactly as implemented. The condition `counts[verdict] > len(valid_votes) / 2` already degrades correctly at one replica: one valid vote satisfies `1 > 0.5` and wins. Zero valid votes remain UNCERTAIN, while explicit multi-replica runs retain the existing majority behavior.

3. Keep sampling's replica default at three. Sampling measures lane behavior and is explicitly outside the ordinary review default policy.

4. Test behavior at the boundaries where defaults are declared: CLI review and gate invocation, plan JSON payload, and Python signatures for discovery and adjudication. Existing explicit-three tests continue to protect opt-in replicated execution without rewriting their fixtures.

## Risks / Trade-offs

- [Single-pass defaults reduce the recall benefit measured for three discovery replicas] → Keep `--replicas N` available and document it as the opt-in heavy-verification mode.
- [A default can drift at one of several declarations] → Assert each declaration through regression tests and synchronize the capability specs.
- [Single-vote adjudication provides no cross-replica corroboration] → Preserve strict-majority semantics transparently and reserve replication for reviews that need additional verification.

## Migration Plan

No data migration is required. Existing commands that require replicated review can pass `--replicas 3` (or another positive count). Reverting the declared defaults restores the previous operational policy without artifact-schema changes.

## Open Questions

None.
