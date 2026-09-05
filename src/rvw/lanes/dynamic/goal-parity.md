---
lane: dynamic/goal-parity
tier: dynamic
schedule_hint: normal
severity_cap: blocker
---

# dynamic/goal-parity

Input: the review brief (declared intent; may be operator-written or derived
from the PR body — the runner marks which). Compare the brief and the diff in
BOTH directions: is everything declared actually done, and is everything done
actually declared? Judge only against the brief. Code quality is other lanes'
job.

Declared but not achieved:

- `dynamic/goal-not-achieved` — the central claim of the brief is not
  implemented, or is implemented in a way that cannot work.
- `dynamic/goal-partially-achieved` — stated scope is partially delivered:
  a listed case/branch/platform is missing while the brief claims completeness.
- `dynamic/declared-missing` — the brief/PR body claims a change (a fix, a
  test, a migration, a doc update) that does not exist in the diff. Include
  claims like "also updated X" where X is untouched. List each missing claim
  verbatim with the brief line it came from.

Done but not declared (the scope-creep detector, ADR-010 D4 — report the
mismatch, never assume the brief is right; a mismatch is a finding even when
the brief itself is inaccurate, especially then):

- `dynamic/undeclared-behavior-change` — user-visible or contract-relevant
  behavior changed without being declared: altered defaults, changed error
  semantics, widened/narrowed accepted inputs, side effects on unrelated flows.
- `dynamic/unrelated-edit` — edits with no plausible connection to the
  declared purpose: drive-by refactors, formatting churn in untouched-logic
  files, config changes the brief never mentions.

## rule: dynamic/goal-not-achieved

The rule is defined by the lane guidance above.

## rule: dynamic/goal-partially-achieved

The rule is defined by the lane guidance above.

## rule: dynamic/undeclared-behavior-change

The rule is defined by the lane guidance above.

## rule: dynamic/unrelated-edit

The rule is defined by the lane guidance above.

## rule: dynamic/declared-missing

The rule is defined by the lane guidance above.
