## Context

`apply_diff_budget` excludes generated globs and per-file segments above 200,000
characters, then packs the retained segments into ordered chunks at or below 400,000
characters each. Discovery is its only consumer for prompt content: `discover.py`
builds one lane prompt per chunk. Every later stage re-reads `target.diff` directly.
`adjudicate.py` appends the raw diff to its candidate list, and `stack_adjudicate.py`
appends the raw descendant diff to its lineage list. See `proposal.md` for the measured
amplification.

The retry asymmetry has the same shape. `stack_adjudicate.py` threads
`retry_invalid_reasons` into `build_presence_prompt`, satisfying
`openspec/specs/stack-review/spec.md`. `dispatch.py` and `adjudicate.py` re-run their
one replacement wave with an unchanged prompt.

## Goals / Non-Goals

**Goals:**

- Stop sending discovery-excluded content to any post-discovery runtime prompt.
- Keep the reviewed content identical across discovery and adjudication for the
  single-chunk case that covers ordinary reviews.
- Give both remaining all-invalid retries the same failure feedback stack presence
  already has.
- Preserve every existing verdict, voting, widening, and coverage behavior.

**Non-Goals:**

- Token, turn, or tool-call ceilings on the runtime process.
- Replica, concurrency, or deadline changes.
- Chunking adjudication or presence prompts.
- Persisting reviewed-diff accounting in run or report schemas.

## Decisions

### Project the reviewed diff in `diffbudget`

Add `reviewed_diff(diff, ...) -> ReviewedDiff` beside `apply_diff_budget`, returning
the concatenation of kept segments plus the same `DiffBudgetReport`. Placing it in
`diffbudget` keeps one owner for exclusion policy, so adjudication cannot drift from
discovery's glob list or size bound. Returning the report as well lets callers state
exactly what was withheld.

A separate exclusion pass inside `adjudicate.py` was rejected: two independent filters
over the same policy is precisely the drift that produced this defect.

### Reuse discovery's exclusion header

The reviewed diff carries the same visible exclusion header discovery prepends, so an
adjudicator can see that content was withheld rather than silently reasoning over a
truncated picture. Withholding the header was rejected because an adjudicator that
cannot tell filtered content from absent content may quote absence as evidence.

### Do not chunk post-discovery prompts

A discovery lane reviews one chunk and reports findings within it. An adjudicator
verifies a specific candidate and may need any kept file to do so, and a presence
recheck answers whether an older claim survives at a new head. Splitting either prompt
would change which evidence a verdict can rest on. Where discovery planned multiple
chunks, adjudication therefore receives the full retained diff, which remains strictly
smaller than today's unfiltered diff.

### Thread invalid reasons through a uniform section

Both new retry prompts render the same `# Retry feedback` section
`build_presence_prompt` already uses, listing `replica <n>: <machine-readable reason>`.
Reusing the established wording avoids inventing a second feedback dialect for the same
failure class. The section appears only on a retry, so ordinary first-wave prompts stay
byte-identical to today's.

For discovery, the reason set belongs to the lane-chunk group whose every initial
replica was INVALID, because that group is exactly the retry unit `dispatch.py`
recomputes.

### Keep the accounting out of persisted schemas

Reviewed-diff characters are a prompt-construction input. Discovery already persists
`DiffBudgetReport` through `DiscoverResult.budget`, so the withheld-content record is
already inspectable and needs no new artifact field.

## Risks / Trade-offs

- [An adjudicator loses context it previously used] → The removed content is limited to
  generated paths and oversized files that no discovery lane was allowed to review, and
  the exclusion header keeps their absence visible.
- [A candidate located in an excluded file becomes unverifiable] → Such a candidate
  cannot exist: findings originate only from lane prompts built from kept chunks.
- [Retry feedback text could leak into a first-wave prompt] → The section is
  constructed only on the retry path and asserted absent on the initial wave.
- [Two filters could still diverge later] → Exclusion policy stays in `diffbudget`
  with a single kept-segment projection used by every caller.

## Migration Plan

Ship without artifact migration. Persisted runs stay readable because no schema
changes. Rollback restores the raw `target.diff` arguments at the two prompt builders
and drops the retry-feedback parameters; no stored data depends on either.
