## Context

An rvw finding ID includes a diff hunk and is stable only while that review's
base and head anchors are unchanged. Reusing that ID to correlate different
stack members would conflate distinct diffs and would miss fixes made outside
the original hunk. The useful durable object is instead the original finding
claim: retain its origin metadata, then ask whether that claim is present in
each descendant checkout.

Stack review also has a larger execution surface than ordinary review. For a
chain of N pull requests it performs N normal reviews, and a naive per-finding
recheck would create unbounded runtime calls. Persistence and fail-closed anchor
checks are required so partial work is inspectable and publication cannot race
a changed chain.

## Goals / Non-Goals

**Goals:**

- Accept an explicit, ordered pull-request list and prove that it is one direct
  same-repository chain.
- Pin every member's base/head refs and SHAs and fail closed when any anchor
  changes.
- Reuse the ordinary review pipeline exactly once per member.
- Re-adjudicate earlier actionable claims against all descendant heads with a
  strict, bounded presence protocol.
- Render one stack report that distinguishes each PR's local findings from the
  current stack-tip state of earlier findings.
- Publish at most one body-only COMMENT review to the tip PR, with dry-run as the
  default.

**Non-Goals:**

- Infer a stack from branch metadata, Graphite, or repository conventions.
- Add `stack gate`, policy/disposition inheritance, or CI blocking semantics.
- Copy a fix disposition from one finding ID to another.
- Comment on every origin PR or emit cross-PR inline comments.
- Run member reviews concurrently.

## Decisions

1. **The caller supplies a comma-separated ordered list.** At least two unique,
   positive pull-request numbers are required. Resolution rejects closed,
   merged, or cross-repository members. For every adjacent pair, the child's
   base ref and SHA must equal the parent's head ref and SHA. There is no
   best-effort reorder or automatic discovery.

2. **The manifest is the immutable stack contract.** Planning captures
   repository identity plus each member's number, URL, title, base ref/SHA, and
   head ref/SHA. Review revalidates the resolved chain before work, checks each
   provisioned detached checkout, and checks the entire chain again after model
   work. Execute publication performs a fresh full revalidation; dry-run
   publication is artifact-only and makes no network call.

3. **Member execution composes the common pipeline.** Review members run
   sequentially in disposable checkouts at their captured heads. The existing
   DISCOVER, MERGE, ADJUDICATE, and REPORT implementation produces ordinary run
   artifacts for each member. The stack directory references those run IDs
   rather than nesting or copying their artifacts.

4. **Lineages preserve claims instead of correlating hunk IDs.** A current
   member contributes its CONFIRMED and unresolved UNCERTAIN ordinary findings
   as new origin lineages only after all older lineages have been checked at
   that member head. Each lineage retains the origin PR, run, public finding ID,
   locations, bodies, severity, and origin verdict. No semantic or hunk-key
   matching is performed between separate ordinary runs.

5. **Presence rechecks are batched by descendant.** At each descendant member,
   all accumulated earlier lineages are evaluated in one presence pass per
   replica rather than one runtime call per lineage. This produces N normal
   reviews plus N-1 batched recheck passes. Prompts contain the immutable origin
   claims and authorize read-only inspection of the full descendant checkout.

6. **Presence has its own strict schema and bounded uncertainty handling.**
   Outputs can only name supplied lineage IDs and vote `PRESENT`, `ABSENT`, or
   `UNCERTAIN`. Missing items vote UNCERTAIN. A wave in which every replica is
   invalid retries exactly once. PRESENT and ABSENT require nonblank source
   evidence or are coerced to UNCERTAIN. Candidates still uncertain receive one
   expanded-context pass at twice the deadline.

7. **Lifecycle states are transition-derived.** A confirmed origin begins
   PRESENT; an unresolved origin begins UNCERTAIN. A final UNCERTAIN observation
   yields `UNCERTAIN`. Otherwise, conclusive observations are read in order:
   final PRESENT with no earlier PRESENT-to-ABSENT transition is
   `STILL_PRESENT`; final PRESENT after an absence is `REGRESSED_IN` at the
   latest ABSENT-to-PRESENT transition; and final ABSENT is `FIXED_IN` at the
   latest PRESENT-to-ABSENT transition. A lineage with no conclusive origin is
   `UNCERTAIN`.

8. **Stack state is strict and file-first.** `/tmp/rvw/<stack-run-id>/` stores
   `stack-manifest.json`, `member-runs.json`, `lineage.json`,
   `stack-report.md`, and eventually `publish-payload.json`. Every JSON artifact
   uses strict versioned Pydantic models. Member-run references are saved after
   each completed review so an operational failure retains partial evidence,
   while a completed stack report requires every planned member.

9. **Publication is one body-only tip comment.** Stack findings span different
   diffs and anchors, so no item is safe to translate into an inline comment on
   the tip PR. The payload hardcodes `event: COMMENT`, uses the generated stack
   report as its body, and targets only the captured tip PR. `--execute` first
   revalidates every member and edge, then sends one review request without a
   422 inline fallback because there are no inline comments.

## Risks / Trade-offs

- [N member reviews plus lineage passes can be expensive] → Run sequentially,
  batch all older lineages once per descendant, default to one replica, and
  expose the existing positive replica override only where needed.
- [A model may mistake moved code for a fix] → Require source evidence for both
  PRESENT and ABSENT, preserve UNCERTAIN, and perform one expanded pass.
- [Origin lineages can overlap when a later ordinary diff independently reports
  the same defect] → Preserve both inspectable claims rather than introduce
  heuristic identity merging in this MVP.
- [A branch can move during a long review] → Capture all anchors, validate
  before and after work, and validate again immediately before execution.
- [Disposable checkouts increase disk and clone cost] → Favor isolated source
  correctness; cleanup remains bounded to checkouts created by the stack run.

## Migration Plan

No existing artifact or CLI migration is required. The nested `stack` commands
and stack artifact schema are additive. Removing the new commands and modules
restores prior behavior without changing ordinary run directories.

## Open Questions

None.
