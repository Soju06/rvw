# Operation modes context

## Purpose and scope

This capability defines how operators and CI enter the common pipeline, how YAML policy converts findings into PASS/BLOCK, how lane quality is sampled and monitored, and which review knowledge belongs inside rvw. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- Owner decisions (2026-07-30 and 2026-08-12): ordinary `review`, `gate`, and `auto` runs keep one discovery replica because lanes x replicas x concurrent rvw instances overloaded `codex-lb`; four concurrent runs were observed demanding up to 64 sessions. Adjudication now defaults independently to three replicas because production reviews dispatched a median of one adjudication run versus eight discovery runs, so majority evidence adds token cost without increasing peak executor sessions.
- Owner decision (2026-08-06): runtime wave concurrency defaults to eight after concurrent rvw runs saturated the shared `codex-lb` account pool, triggering local `account_stream_cap` overload, 30-second retry sleeps, and lane INVALIDs. Operators can set a positive `--concurrency` value on every command capable of runtime execution.
- ADR-009 keeps one stage implementation while providing `review` and `auto` command surfaces. Policy handles reproducible inclusion/severity decisions after model-based factual adjudication.
- The implemented pause point is after MERGE. This supersedes ADR-009 D2's original wording that pause occurred after ADJUDICATE.
- Approval is not expressible. Policy allows only `comment` or `none`; `--allow-approve` prints a placeholder warning and does not change publication event type.
- ADR-013 chose a standalone Python CLI. The current package floor is Python 3.12+ (not the ADR's original 3.11+), built with uv, Typer, and Pydantic v2 and published under `rvw`.
- The lane sampling gate follows the measured enum/free parity experiment and the 2026-07-28 19-lane batch. Eight site-based REVIEW results contained zero novel free rule IDs; they were replica site variance, so PASS now means no free rule ID falls outside the actual closed enum.
- Doctor exposes the feedback loop implied by ADR-004/005: invalid counts, `/other` rates, adjudication rejection rate, unresolved residue, and evidence coercions.
- ADR-014 keeps review execution mechanics in rvw while implementation delegation stays in external executor profiles. Skill/docs diet is safe only after real review coverage is proven; PR #1119 provided a 39/39-valid run with 410s discovery and 197s adjudication.
- Stack review extracts the ordinary pipeline into reusable execution and
  loading helpers, then invokes that same implementation once per captured
  member. Stack-specific code owns only chain sequencing, immutable anchors,
  presence rechecks, and stack-level artifacts.
- Stack member discovery uses the discovery replica count, while ordinary
  member adjudication and descendant presence checks use the independent
  adjudication replica count.

## Constraints

- `review` does not itself apply the auto YAML policy; `auto` calls the shared pipeline and then evaluates policy.
- Without `--repo-dir`, the common pipeline skips adjudication and renders unadjudicated findings; a confirmed-only auto policy therefore cannot block those groups.
- The `auto` command uses the default external registry and default run root rather than exposing all review command overrides.
- Sample gap detection compares rule-ID sets against the lane enum. `(file, line)` differences remain a separate variance signal and body text is not semantically compared.
- Doctor reads only persisted runs with `discover.json` and defaults to the newest 20.
- Stack members run sequentially and do not inherit auto policy or gate
  dispositions; presence adjudication is a separate claim-status pass after
  each ordinary member review.

## Failure modes

- A permissive drop/promote/block policy can produce an unintended PASS.
- Missing policy files fail before the pipeline runs.
- `--allow-approve` can mislead callers if they ignore the warning; it has no enabling effect.
- Sampling is model-driven and can vary between runs despite equal replica counts.
- Sampling uses the production diff planner and scales as two variants x replicas x chunks, while comparison still unions valid findings by variant.
- Existing consumers still see only `PASS` or `REVIEW`; they must inspect `site_variance` when they need replica-distribution detail.
- Doctor's rates can be distorted by a small recent-run sample and do not validate registry predicates.
- Premature removal of external review guidance can leave a repo without a proven rvw lane replacement.
- Long explicit stacks multiply ordinary review work and descendant presence
  passes; there is no concurrent-member mode in the initial stack capability.

## Concrete example

```yaml
promote_to_blocker:
  agreement_at_least: 2
  severity_at_least: warning
drop:
  agreement_at_most: 1
  severity_at_most: suggestion
block_when:
  severity_at_least: blocker
  confirmed_only: true
publish_state: comment
```

A one-replica suggestion is dropped. A two-replica confirmed warning is promoted to blocker and makes `rvw auto` exit 1. A REJECTED blocker is excluded, and an unresolved blocker does not block while `confirmed_only` is true. Publication, if enabled, remains a COMMENT review.

## Historical deltas

- ADR-009 D1 described `rvw review` as default auto plus `--pause`; implementation exposes separate `review` and `auto` commands over shared internals.
- ADR-009 D2's post-ADJUDICATE pause is superseded by the implemented post-MERGE pause.
- ADR-009 mentioned explicit approval opt-in; approval is currently impossible, and `--allow-approve` is only a warning placeholder.
- ADR-013 specified Python 3.11+ and pyright; current packaging requires Python 3.12+ and uses `ty check`.
- Before stack support, common stage execution lived directly in the CLI.
  Extracted pipeline helpers now preserve the same review, auto, report, and
  gate behavior while allowing ordered member composition.
