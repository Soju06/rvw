# Adjudication context

## Purpose and scope

Adjudication is a machine stage that checks merged claims against the target checkout. It does not discover, rank, summarize, or publish findings. See [spec.md](spec.md) for normative behavior.

## Key decisions and measured basis

- ADR-007 locates the separation between discovery and adjudication rather than between machine and human. Automatic quality is the goal; a human pause is optional operation policy.
- A measured nine-candidate fixture contained six genuine and three fabricated claims. Adjudication rejected all 3/3 fabricated claims, leaked none, and wrongly rejected 0/6 genuine findings. Five genuine claims were confirmed and one genuine cache-key issue remained UNCERTAIN because needed context was outside the diff.
- ADR-008 turns that uncertainty into a single wider pass. The real PR #1119 smoke adjudicated 13 collapse groups with three unanimous replicas in about 197 seconds after DISCOVER took about 410 seconds.
- Owner decision (2026-07-30): one adjudication replica is the ordinary default, while multiple replicas remain opt-in heavy verification for high-stakes or large-scope reviews.
- Missing items become UNCERTAIN votes so a model cannot create an implicit rejection by omission. Majority is strict (`> 50%`), making ties uncertain; at the one-replica default, one valid vote wins because `1 > 1 / 2`.

## Constraints

- The current runtime may be the same Codex model used for discovery, so shared blind spots remain possible.
- The expanded prompt authorizes broad exploration of definitions, callers, and tests; it is not programmatically limited to a computed symbol set.
- The evidence coercion checks only that text is non-empty. It does not mechanically prove the text is a verbatim source quote.
- Invalid replicas do not cast votes; a pass with no valid outputs yields UNCERTAIN with an empty vote list.

## Failure modes

- Same-runtime confirmation can reinforce a shared misconception.
- A valid output can omit candidates; those omissions correctly reduce confidence but may make large batches uncertain.
- A fabricated non-empty evidence string can pass the mechanical REJECTED guard, although the prompt requires source quotation.
- Repository checkout mismatch can ground verdicts in the wrong source because head identity is not re-verified by this stage.

## Concrete example

In an explicit three-replica pass for candidate `abc`, the valid replicas return CONFIRMED, REJECTED with no evidence, and omit the candidate. The second vote is coerced and the omission becomes another UNCERTAIN, producing votes:

```text
CONFIRMED / UNCERTAIN / UNCERTAIN
```

No verdict has a strict majority, so `abc` receives the expanded pass at twice the deadline. If two expanded replicas then CONFIRM it, the final verdict is CONFIRMED; otherwise an uncertain result remains explicitly unresolved.

## Historical deltas

ADR-007 required verdict evidence to quote source. The implementation strongly prompts for verbatim quotes but enforces only non-empty evidence for REJECTED votes. ADR-008 proposed capping expansion to directly referenced symbols; the current prompt permits enclosing code, definitions, callers, and relevant tests without a mechanical traversal cap.
