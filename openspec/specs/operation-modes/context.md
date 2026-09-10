# Operation modes context

## Purpose and scope

This capability defines how operators and CI enter the common pipeline, how YAML policy converts findings into PASS/BLOCK, how lane quality is sampled and monitored, and which review knowledge belongs inside rvw. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- Owner decision (2026-09-07): rvw keeps two review surfaces, the CLI on a host or in
  the project image and the GitHub App webhook path. The reusable GitHub Actions review
  workflow was retired because it had no consumers, duplicated the Codex credential into
  every consumer repository, and could not use the App's egress-proxy credential
  injection; its measured basis is recorded in the container-ci-packaging context.
- 2026-09-02: The project image packages Python 3.12, Node 24, Codex 0.152.0,
  rvw and the common lanes behind one argument-preserving entry point. It was first
  driven by a protected base-side Actions caller invoking `rvw auto` against an immutable
  head checkout, with the 0/1 auto status as the job check and COMMENT as narrative
  output; that caller is retired and the image is now invoked directly or by the App.
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
- Approval is expressible only through the repository `publish` policy with its explicit opt-in (2026-09-08); `publish_state` allows only `comment` or `none`; absent explicit channels, `none` disables review publication, and `--allow-approve` prints that it has no effect and never changes the event.
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

- Direct container runs mount the target checkout read-only at `/workspace` behind a
  read-only container root, as `docs/container-image.md` shows; the App Sandbox
  provisions its own checkout and enforces its own boundary. Project `.rvw/` policy and
  lanes resolve from the captured base commit, not from the pull-request head.
- `review` applies the auto YAML trigger policy before discovery without applying its verdict rules; `auto` translates compatibility options into the shared `run` policy-gated command.
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
- `--allow-approve` can mislead callers if they ignore the warning; it has no enabling effect, and approval requires two keys in the base-ref policy.
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

A one-replica suggestion is dropped. A two-replica confirmed warning is promoted to blocker and makes `rvw auto` exit 1. A REJECTED blocker is excluded, and an unresolved blocker does not block while `confirmed_only` is true. Publication, if enabled, is a COMMENT review under this policy; adding `publish: {on_block: request_changes, dismiss_on_pass: true}` makes BLOCK request changes and a later clean head dismiss that request.

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

The audit also found that Actions and App checked out event SHAs without passing them to Python, and that a PR URL did not bind the numbered `gh pr view/diff` calls (`src/rvw/target.py:172–212`, `.github/workflows/rvw-review.yml:39–75`, `cloud/worker/src/sandbox-auth.ts:107–119`, baseline lines). The App adapter now passes both anchors and Python binds repository operations; the Actions adapter did the same until its 2026-09-07 retirement. Host agentic execution already provisioned a checkout when `--repo-dir` was absent; the prior constraint claiming it always skipped adjudication was stale. `run` owns policy-gated automation while `review` retains its existing interactive/pause role.

## Publication locale enforcement (2026-09-07)

The --allow-language-fallback option is available on publication-capable commands; auto policy accepts the strict boolean allow_language_fallback, default false. An explicit CLI opt-in or true selected policy permits original mismatched prose only after the one rewrite opportunity and records actual fallback use. Merely enabling fallback does not mark use when language passes. A persistent mismatch uses the existing infrastructure category (infra_failed, exit 3), preserving 0/1 for policy PASS/BLOCK and 2 for invalid presentation/configuration. The App still finishes its localized check without publishing finding prose.

## No-output timeout (2026-09-08)

`review`, `run`, `auto`, `gate`, and `stack review` expose `--no-output-timeout` with the same 1 to 1800 CLI bounds as `--deadline`; `sample` and `adjudicate` keep the runtime default and read neither the option nor the environment variable. Precedence is the explicit option, then `RVW_NO_OUTPUT_SECONDS`, then 660 seconds, resolved once at command start and passed to every discovery, adjudication, expanded, and stack-presence runtime the command constructs. The publication language rewriter keeps the runtime default: its rewrite deadline is capped at 60 seconds, so the 660-second watchdog is inert there by construction. A present but malformed environment value fails closed before any runtime work: `run` and `auto` resolve it inside the `configuration` stage so the failure is recorded as `invalid_configuration` with exit 2 and the process contract intact, mirroring `RVW_HOST_CONCURRENCY`, while `review`, `gate`, and `stack review` print the error and exit 2 before their pipelines start. `run` and `auto` also append the effective value to the canonical command so `process.json` records the watchdog that actually governed the run even when it came from the environment or the default.

## Publish event override and mode rename (2026-09-08)

`rvw publish --run` re-evaluates the policy verdict from the persisted merge and outcome and accepts `--event` only as a downgrade to COMMENT; nothing on the command line escalates past the repository policy, so an operator with a stale checkout cannot approve or request changes by hand through rvw. The App publish mode is renamed `github-review` because the Python side now chooses the event; `github-comment` stays accepted for one release with a deprecation warning and is normalised before the process contract records it.

## Codex model and reasoning-effort override (2026-09-08)

Four consecutive production App runs on the consuming repository at a 900 s deadline showed the `correctness`, `hygiene`, and `test-integrity` lanes hitting the deadline on every attempt while stating that every changed region was covered and a final evidence pass was underway, then continuing to call tools: 35 to 94 tool calls per dead lane against 5 to 19 for lanes that finished, unchanged by the 0.15.0 prompt budget contract. The owner wants to A/B the reasoning effort (`medium`, `high`) and the model (a `gpt-6` variant) against the packaged `gpt-6-astra` / `max` before touching lane prompts, which needs a per-run override with no code change on both surfaces. The CLI side of that is the requirement "Runtime-executing commands expose the Codex model and reasoning effort" in [spec.md](spec.md); the resolver, enum, and artifact recording are described in the runtime-contract context.

`review`, `run`, `auto`, `gate`, `stack review`, `sample`, and `adjudicate` expose `--model` and `--reasoning-effort`. Precedence per field is the explicit option, then `RVW_CODEX_MODEL` / `RVW_CODEX_REASONING_EFFORT` (not consulted when the option is given), then the packaged default; the effort must be one of the nine Codex 0.152.0 names (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `persistent`) and the model any non-empty trimmed string. The command shape mirrors `--no-output-timeout`: `review`, `gate`, `stack review`, `sample`, and `adjudicate` resolve the policy as their first statement, before the host gate, and exit 2 with the resolver's message naming the option or variable; `run` and `auto` resolve it inside the `configuration` stage right after the watchdog, so a malformed value finalizes `process.json` with `invalid_configuration`, exit 2, and a detail naming the source while the process contract the App reads stays intact. Unlike the watchdog option, `sample` and `adjudicate` expose the flags although they read no watchdog environment: a sample or re-adjudication run has to be attributable to a cell like any other, and `adjudicate --run` may be the cheapest way to compare adjudication behaviour across efforts on one persisted discovery.

The resolved policy is threaded through `_execute_pipeline`, `_review_pipeline`, `_gate_pipeline`, `_stack_review_pipeline`, `_adjudicate_existing_run`, and `sample` to every `CodexRuntime` the command constructs (discovery with its retry and coverage redispatch, initial and expanded adjudication, stack presence, sample, re-adjudication); the publication language rewriter alone keeps the packaged default because its 60 s translation is not part of the measurement. `run` and `auto` record the effective values under `runtime.model` / `runtime.reasoning_effort`, as `model=` / `reasoning_effort=` in `environment.txt`, and append `--model <m> --reasoning-effort <e>` to the canonical command after `--no-output-timeout <n>`, so a run whose cell came from a forgotten host variable is still legible from its first `process.json`. Validation happens at this resolver boundary and not in the `CodexRuntimePolicy` value object, which stays permissive because Codex itself accepts a `Custom` effort string.

The A/B plan is four cells on the same consuming-repository pull requests: default `max`, `medium`, `high`, and the `gpt-6` variant; per cell the comparison reads the dead-lane count and reasons from `summary.json failed_lanes`, `tool_calls` per lane and attempt from `usage.json`, and the per-wave wall from `summary.json wave_wall_seconds`, alongside the confirmed finding counts. A worked example: `RVW_CODEX_REASONING_EFFORT=medium rvw run --target <pr> --policy auto` runs every lane at `gpt-6-astra` / `medium` and records `--reasoning-effort medium` in its canonical command, while `rvw run --target <pr> --policy auto --reasoning-effort high` in the same shell ignores the variable and records `high`; `RVW_CODEX_REASONING_EFFORT=maximum rvw run ...` exits 2 with `invalid_configuration` before any lane starts.

## Repository publication controls (2026-09-10)

The owner principle is that choices a consuming repository could reasonably make differently belong in `.rvw/`. The publication subset of the hardcode audit includes two synthesis defects from #95: its universal language example named a Gmail inventory error copied from a bori fixture, and its blanket vocabulary ban rejected the bori #1772 discovery-domain explanation even though finding paths name `life-gmail-discovery-reconciliation`. The generic language example now demonstrates Korean prose with unchanged English identifiers in backticks; repository examples follow it. Source occurrences establish domain vocabulary for that review, and allowed terms offer a repository escape hatch without relaxing literal fidelity.

The anchored presentation snapshot owns `voice.examples`, `voice.allowed_terms` and `synthesis.enabled`; the anchored auto policy owns channels, check conclusions and inline placement. Missing keys preserve existing defaults. Explicit channels take precedence; legacy `publish_state: none` maps to checks only when channels are absent. Disabling checks still terminalizes the mandatory bootstrap check as neutral. Invalid/infrastructure/deadline outcomes cannot be configured to succeed.

Inline selection applies the severity floor, then a highest-severity cap with finding-key ties. Selection precedes living-thread reuse, so reused candidates can reduce newly posted comments below the cap. Body-only findings retain their full explanation. Body-only findings still participate in identity matching, preventing a placement change from being mistaken for fix evidence; their matched threads are excluded from reuse and write plans; historical disappeared findings retain the existing fix-proof rules. `threads.resolve_on_fix` and `threads.reuse_open_thread` apply within that boundary. A zero cap selects no inline candidates. The channel and placement facts remain available in summary artifacts and enabled check details.

Operator examples and all defaults are documented in [auto policy controls](../../../docs/auto-policy.md). The active change is [repository-publication-controls](../../changes/repository-publication-controls/proposal.md).

## Repository review triggers (2026-09-10)

The owner measured clawroid/bori#1772, a Changesets release pull request by
`github-actions[bot]` on `changeset-release/main`, receiving 22 reviews, one per bot
push. The same pattern occurred on #1743, #1749, #1751, and #1753. Audit rows A1–A3
in `/tmp/rvw-hardcode-audit.md` identified eligibility and draft checks as hardcoded
Worker decisions. Consumers now name their bots and repository conventions in the
base-ref `.rvw/policies/auto.yaml`; packaged defaults contain no bot logins.

Missing configuration retains the empty denylist and draft skip. A matched denylist
rule supplies the human skip reason; an allowlist miss has no matching rule, so it
records null and says that no allowlist rule matched. Draft skips also record null
in CLI summaries, while the App retains the historical no-check draft path. Explicit
reruns honor the human request. Trigger facts cross the App/CLI boundary so container
metadata changes cannot undo the pre-enqueue decision or erase its diagnostics.

The publication-controls integration applies the resolved presentation locale to trigger skips as well as completed results. Interactive skips persist the anchored presentation before rendering; matching rule names remain unchanged and draft/allowlist explanations use the English/Korean catalogs.
