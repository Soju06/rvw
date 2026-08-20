# Stack review context

## Purpose and scope

This capability composes ordinary rvw reviews into an explicit pull-request
stack and answers whether a finding from an earlier member is still present at
each descendant head. It owns ordered input, direct-chain validation, immutable
anchors, lineage presence adjudication, stack artifacts, and tip-only
publication. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- A finding ID contains hunk identity and is stable only for one unchanged
  base/head pair. Stack review therefore retains the origin claim and
  re-adjudicates it against descendant source instead of correlating hunk IDs
  from different ordinary runs.
- Stack membership is explicit. At least two unique PR numbers are supplied in
  parent-to-child order; every adjacent child's base ref/SHA equals its parent's
  head ref/SHA. Automatic discovery and best-effort reordering would make the
  reviewed chain ambiguous.
- Every member runs the existing DISCOVER, MERGE, ADJUDICATE, and REPORT
  pipeline in a disposable checkout. Its diff uses the captured
  base/head merge base so an advanced base does not appear as reverse changes.
  Stack orchestration adds sequencing and lineage work rather than maintaining
  a second review implementation.
- At each descendant, all earlier lineages are checked in one batch per
  replica. A stack of N members therefore performs N ordinary reviews plus N-1
  batched presence passes, rather than one model call per finding.
- Presence has a distinct strict schema and deterministic `L1`, `L2`, ...
  batch-local IDs that are mapped back to persisted lineage IDs. Duplicate IDs
  are invalid, PRESENT and ABSENT require current source evidence, missing items
  are UNCERTAIN, an all-invalid wave retries once with its invalid reasons, and
  uncertain residue receives one expanded-context pass.
- The descendant diff in a presence prompt is the budget-filtered reviewed diff,
  the same projection discovery uses. A seven-member simulation with ten
  confirmed findings per member and a 100,000-character diff accumulated
  2,677,698 presence prompt characters, of which 1,800,972 were repeated diff
  content; sending unfiltered generated segments through that quadratic path
  multiplied the waste at every descendant.
- Publication is one body-only COMMENT on the tip. Cross-head claims do not have
  safe inline anchors in the tip diff, and origin-member comments would create
  duplicated or stale review state. The request pins `commit_id` to the
  captured tip SHA so GitHub cannot select a newer head after revalidation.
- Observation arrays follow manifest position; PR numbers are identities and
  may decrease between a parent and child. Completed histories are checked
  against the corresponding manifest suffix.
- Stack review announces the run ID as soon as its artifact directory exists,
  using stderr in JSON mode to keep stdout machine-readable.

## Constraints

- Members are limited to one GitHub repository and must remain open and
  unmerged.
- Member reviews run sequentially and default to one replica; explicit
  replication multiplies both ordinary and presence work.
- Confirmed and unresolved ordinary findings become independent origin
  lineages. A later ordinary finding is not heuristically merged with an older
  lineage even when their prose overlaps.
- An unresolved origin remains an uncertain lineage because its presence at the
  origin head was never established conclusively.
- Stack review does not apply auto policy, gate dispositions, inherited
  dispositions, or blocker authority checks.

## Failure modes

- Long stacks can be expensive because every member receives a full ordinary
  review in addition to descendant presence passes.
- A model can misclassify moved code as fixed; nonblank current-source evidence
  and explicit UNCERTAIN residue reduce but do not eliminate that risk.
- A member that moves during execution leaves partial member-run and lineage
  artifacts but no completed stack report; the early run ID identifies those
  artifacts for recovery.
- Fork-based stacks whose child cannot directly target the parent's head branch
  in the same repository are rejected by the same-repository direct-edge
  contract.
- Independently rediscovered versions of one semantic defect can appear as
  separate lineages because heuristic cross-run identity is intentionally out
  of scope.
- A push after revalidation can still make a commit-pinned review stale, but it
  cannot make GitHub attach that review to an uncaptured newer head.

## Concrete example

```bash
rvw stack plan --prs 101,102,103
rvw stack review --prs 101,102,103
rvw stack publish --run <stack-run-id>
```

If a CONFIRMED PR 101 claim is PRESENT at PR 102 and ABSENT at PR 103, its
lineage is `FIXED_IN #103`. If it later becomes PRESENT again, the latest
ABSENT-to-PRESENT transition becomes `REGRESSED_IN`. A final UNCERTAIN
observation always keeps the current summary UNCERTAIN.

## Historical deltas

This capability was introduced as an explicit-list MVP. Automatic stack
discovery, `stack gate`, per-origin PR comments, inline stack comments, and
disposition inheritance remain outside its contract.
