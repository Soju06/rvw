# Operation modes context

## Purpose and scope

This capability defines how operators and CI enter the common pipeline, how YAML policy converts findings into PASS/BLOCK, how lane quality is sampled and monitored, and which review knowledge belongs inside rvw. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- 2026-09-02: The project image packages Python 3.12, Node 24, Codex 0.152.0,
  rvw and the common lanes behind one argument-preserving entry point. A protected
  `pull_request_target` caller invokes `rvw auto` against an immutable head checkout;
  the 0/1 auto status is the job check and COMMENT remains narrative output.
- 2026-09-01: Review, auto, gate, stack review, and plan select agentic discovery by default and expose `inline` as the compatibility path. Sampling stays inline because it compares schema variants over a fixed diff fixture.
- Owner decisions (2026-07-30 and 2026-08-12): ordinary `review`, `gate`, and `auto` runs keep one discovery replica because lanes x replicas x concurrent rvw instances overloaded `codex-lb`; four concurrent runs were observed demanding up to 64 sessions. Adjudication now defaults independently to three replicas because production reviews dispatched a median of one adjudication run versus eight discovery runs, so majority evidence adds token cost without increasing peak executor sessions.
- Owner decision (2026-08-06): runtime wave concurrency defaults to eight after concurrent rvw runs saturated the shared `codex-lb` account pool, triggering local `account_stream_cap` overload, 30-second retry sleeps, and lane INVALIDs. Operators can set a positive `--concurrency` value on every command capable of runtime execution.
- Owner decision (2026-08-14): the runtime base deadline remains 600 seconds, and every runtime-executing command exposes `--deadline` from 1 through 1800 seconds. The ceiling is three times the established default and bounds the existing doubled expanded pass at one hour; PR #1119 completed 39 valid discovery runs with about 410 seconds of stage wall time, so raising the global default was not justified.
- 2026-08-12: Per-process semaphores do not bound a shared host: six processes at the default capacity of 8 implied 48 theoretical runtime streams. Runtime commands therefore share a host-local flock gate capped at 12 by default; the effective bound is the smaller of the process and host caps, while `RVW_HOST_CONCURRENCY=0` disables the host gate.
- 2026-08-12: On Linux, spawned runtime wrappers use the exec-side `setpriv --pdeathsig SIGTERM` command prefix. This avoids thread-unsafe `preexec_fn` work and normally prevents a SIGKILLed rvw process from releasing its flock while an orphaned timeout/codex execution continues consuming a gateway stream. Linux fails closed if `setpriv` is unavailable; other platforms do not guarantee this coupling. The tiny pre-`setpriv` orphan race is accepted.
- The ambient `XDG_RUNTIME_DIR` is validated without mutating its permission contract. Rvw-owned `rvw-slots` and `c{cap}` directories are normalized and descriptor-verified at 0700, `O_NOFOLLOW` is mandatory, and slot files are opened relative to a held validated directory descriptor.
- Contention uses nonblocking randomized scans separated by cancellable, jittered async sleeps capped at 0.25 seconds. This avoids stranded executor threads at the accepted cost of no kernel FIFO fairness. Each spawned runtime wrapper leads a dedicated process group; cancellation or other exceptional unwind signals the whole group, escalates to `SIGKILL` after five seconds when needed, records that escalation in the run log, and reaps the wrapper before releasing the host slot.
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
- Re-adjudication opens an existing run and invokes only the shared adjudication stage against an explicit checkout. It writes a timestamped runtime-attempt directory and replaces the outcome and report only after a valid outcome exists, so an infrastructure failure cannot erase a prior successful result.
- Build identity is captured by the PEP 517 wrapper or a deterministic package-byte fallback. Runtime commands expose that identity without consulting mutable Git state; a stale-install warning is emitted only when a local source checkout is proven to be a descendant of an embedded clean commit.

## Constraints

- Container CI mounts the target repository read-only at `/workspace`; project `.rvw/`
  policy and lanes continue to resolve from the immutable base-side contract.
- `review` does not itself apply the auto YAML policy; `auto` translates compatibility options into the shared `run` policy-gated command.
- `adjudicate --run` requires persisted target, discovery, and merge inputs and never repeats discovery. A failed attempt may update `run.json` with its error while retaining the previous outcome and report.
- Agentic execution without `--repo-dir` provisions a checkout used by discovery and adjudication. Inline execution without a checkout can render unadjudicated findings, which a confirmed-only policy does not block.
- `run` and `auto` use the ordinary layered lane loader and support an explicit artifact directory; interactive pause and worktree-rule overrides remain `review` concerns.
- Sample gap detection compares rule-ID sets against the lane enum. `(file, line)` differences remain a separate variance signal and body text is not semantically compared.
- Doctor reads only persisted runs with `discover.json` and defaults to the newest 20.
- Stack members run sequentially and do not inherit auto policy or gate
  dispositions; presence adjudication is a separate claim-status pass after
  each ordinary member review.
- The host cap is configured only through `RVW_HOST_CONCURRENCY`; it is local to one host and does not change `--concurrency` semantics.
- The 1800-second deadline ceiling is enforced at the CLI boundary. Direct Python callers preserve the existing positive-deadline contract, and an expanded adjudication or stack-presence pass receives twice the selected base value.
- Cap-sharded `c{cap}` directories intentionally avoid cross-cap deadlock. Operators changing `RVW_HOST_CONCURRENCY` while processes are active temporarily run disjoint pools without one shared bound; the host bound converges when configurations converge.
- Contending acquisition polls all slots and does not promise FIFO fairness; a newly freed slot can take up to the capped polling interval to be observed.

## Failure modes

- A permissive drop/promote/block policy can produce an unintended PASS.
- Missing explicitly selected policies and malformed selected policies fail before the pipeline runs; absent repository/external policies select the package default.
- `--allow-approve` can mislead callers if they ignore the warning; it has no enabling effect.
- Sampling is model-driven and can vary between runs despite equal replica counts.
- Sampling uses the production diff planner and scales as two variants x replicas x chunks, while comparison still unions valid findings by variant.
- Existing consumers still see only `PASS` or `REVIEW`; they must inspect `site_variance` when they need replica-distribution detail.
- Doctor's rates can be distorted by a small recent-run sample and do not validate registry predicates.
- Premature removal of external review guidance can leave a repo without a proven rvw lane replacement.
- Long explicit stacks multiply ordinary review work and descendant presence
  passes; there is no concurrent-member mode in the initial stack capability.
- A permitted high deadline can hold a host-global slot for 1800 seconds, or 3600 seconds during the one expanded pass; larger discovery work must be split through the existing chunk planner.

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

## Unified execution contract evidence (2026-09-05)

The 132-line `/tmp/rvw-surfaces-analysis.md` audit inspected v0.11.5 (`613201f`) and passed all 12 main specifications before its failure injections. A failed review summary plus empty merge returned `review → 3` but `auto → PASS/0`; infrastructure and missing-policy auto injections returned exit 1 with empty stdout (`src/rvw/cli.py:669–676,1666–1686,1709–1756`, `src/rvw/summary.py:106–113`, `src/rvw/adjudicate.py:318–326`, baseline lines). The common `run` boundary now checks execution health before deterministic policy evaluation and reserves 0/1/2/3 for pass/block/invalid/infra.

The audit also found that Actions and App checked out event SHAs without passing them to Python, and that a PR URL did not bind the numbered `gh pr view/diff` calls (`src/rvw/target.py:172–212`, `.github/workflows/rvw-review.yml:39–75`, `cloud/worker/src/sandbox-auth.ts:107–119`, baseline lines). Event adapters now pass both anchors and Python binds repository operations. Host agentic execution already provisioned a checkout when `--repo-dir` was absent; the prior constraint claiming it always skipped adjudication was stale. `run` owns policy-gated automation while `review` retains its existing interactive/pause role.
