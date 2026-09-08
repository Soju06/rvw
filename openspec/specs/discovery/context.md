# Discovery context

## Purpose and scope

DISCOVER resolves active lanes into bounded runtime work, supplies each lane the right diff and intent context, and enriches only valid runtime output. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- 2026-09-01 owner decision: checkout-backed agentic discovery is the default. Prompt budgets, generated-path exclusions, and chunking remain only for explicit inline fallback and sampling; controller hunk parsing now verifies receipts and anchoring without injecting diff text.
- Coverage receipts are unioned per lane across VALID outputs. One representative run per incomplete lane forms a single separate coverage wave; remaining canonical hunk IDs are persisted visibly rather than triggering an unbounded loop.
- ADR-005 makes `unscoped-sweep` the structural coverage net. On a six-defect fixture, the scoped slop lane found 0/3 deep defects in both enum and free-ID conditions, while the sweep found 3/3. Its warning cap contains the higher expected false-positive rate.
- ADR-006 measured the benefit of three replicas. Eight repeated runs showed an individual run recovered about 88% of the union; three replicas raised expected union recall to about 99%, while four added little. The 2026-07-30 owner decision keeps discovery replication as opt-in heavy verification and makes one discovery replica the ordinary default to avoid executor overload across concurrent rvw runs; the 2026-08-12 split decouples that count from adjudication.
- Concurrency tests on a 22-core host found N=4, 8, and 16 completed in 49.1, 50.0, and 50.6 seconds. After concurrent rvw processes saturated the shared account pool on 2026-08-06, the default cap was reduced to 8 while retaining an explicit positive override, one wave, and heavy-first LPT ordering.
- The runtime deadline remains 600 seconds by default. Operators can select a 1-through-1800-second base deadline through runtime-executing CLI commands; the ceiling is three times the established default and prevents one dispatched runtime from pinning a host-global slot for hours.
- 2026-08-12: Process-local semaphores multiply across concurrent rvw processes. Six processes at the per-process default of 8 implied 48 theoretical runtime streams, following the 2026-08-06 account-pool saturation incident that produced selection retries and 503 degraded-mode lane failures. A host-global default cap of 12 now bounds aggregate runtime streams; the effective bound is the smaller of the process and host caps, and `RVW_HOST_CONCURRENCY=0` disables only the host gate.
- 2026-08-12: Replacement-wave directory reuse reproduced destruction of initial INVALID evidence, motivating distinct `retry/` artifact directories.
- 2026-08-12: PR #16 self-review finding `c1476eb7` confirmed that retry discarded the initial `invalid_reason`, motivating persisted ordered attempt coverage.
- A real one-chunk PR #1119 run dispatched 13 lanes x 3 replicas and completed DISCOVER in about 410 seconds with all 39 runs valid. ADJUDICATE then took about 197 seconds.
- The same PR contained a 2.84 MB generated `contract-graph.json` inside a 2.87 MB diff. Excluding it left 26,195 characters of reviewable source and motivated visible, file-level diff budgeting.
- On 2026-07-28, three `apifuse-provider-tabelog` worktree reviews retained 734,985 characters and `codex-lb` PR #1520 retained 464,425 characters. Both were legitimate source review units, so the 400,000-character aggregate limit now bounds one prompt and expands work into ordered whole-file chunks instead of rejecting the review.
- 2026-08-21: adjudication and stack presence recheck were found re-embedding the unfiltered target diff, returning excluded generated and oversized segments to prompts. The exclusion policy therefore also exposes an unpartitioned reviewed-diff projection so post-discovery stages share one owner for that policy instead of re-implementing it.
- 2026-08-21: the all-invalid replacement wave was found re-sending a byte-identical prompt, so it now carries that lane-chunk's prior invalid reasons in the same form stack presence recheck already used.
- Final planned execution loss is evaluated separately from retry history. Ordered attempts remain the audit trail, while the final diagnostic and normalized reason drive strict coverage status: mixed valid/invalid execution is degraded and all-invalid planned execution is failed.

## Constraints

- Agentic prompts intentionally omit dynamic briefs and cross-lane covered-rule sections to keep the prompt limited to the lane document, SHA range, and output instructions. Inline mode retains both injections.
- Uncommitted and root-commit targets have no two-anchor range and therefore require explicit inline mode.
- The code does not hardcode `unscoped-sweep`; its mandatory status depends on the external default registry keeping it in a predicate-free base layer.
- The covered-rules section is prompt guidance. The strict schema prevents foreign IDs but cannot prove the model avoided semantically duplicate findings.
- The default per-file and per-chunk limits are characters, not tokens or bytes.
- Cross-chunk prompts list all kept paths and mark the current subset, but do not duplicate other chunks' source text.
- Per-process concurrency above 16 has not been measured; operators who override the defaults are responsible for matching shared gateway capacity.
- Direct discovery callers preserve any positive deadline for API compatibility; the 1800-second ceiling applies to CLI operator input.
- PR fallback uses title and body; linked issues from ADR-010 are not resolved by the current target model.

## Failure modes

- A base registry missing `unscoped-sweep` creates a silent coverage gap.
- A generated file not matched by the default globs may create extra chunks and model work.
- The exclusion header is rendered once by a shared helper. Rebuilding the unpartitioned reviewed diff by joining chunk text would restate that header once per chunk, and only the intersection of a nonempty exclusion set with a multi-chunk retained diff exposes it; a test covering either condition alone passes.
- If all replicas remain invalid after the replacement wave, the lane contributes no findings but remains visible with zero valid coverage.
- Successful lane findings survive a degraded run, but the run summary, CLI JSON, and report label them as partial and identify every failed lane execution.
- Missing, duplicated, unexpected, or invalid lane-replica-chunk coverage remains a fail-closed gate condition.
- A PR body can be wrong or adversarial; it is intent provenance, not correctness evidence.
- Empty or malformed diffs can fail file segmentation instead of reaching a runtime.

## Concrete example

Given active lanes `security-exposure`, `dynamic/edge-cases`, and `unscoped-sweep`, default discovery builds three planned runs with one chunk and six with two chunks. Explicit `--replicas 3` heavy verification builds nine and 18 respectively. The sweep prompt lists both other lanes' closed rule IDs as already covered. In the explicit three-replica mode, if one security replica on one chunk times out, its two valid outputs are still enriched with hunk IDs and that lane-chunk is not retried. If all three dynamic replicas on one chunk are invalid, only that lane-chunk gets one replacement wave.

For a diff containing `runtime-snapshots/contract-graph.json` plus `src/client.ts`, the generated segment is excluded and the prompt begins with a line such as:

```text
# rvw: 1 files excluded from review diff (generated/oversize): runtime-snapshots/contract-graph.json
```

## Historical deltas

ADR-010 specified title, body, and linked issues; the implementation carries only title/body. The historical plan also described a single wave as if every run were simultaneously active, while the implemented semaphore queues a single submitted wave at default concurrency 8.

## Publication locale enforcement (2026-09-07)

The configured locale is an output contract in shared discovery instructions, including agentic minimal prompts, inline prompts, replacement retries and coverage waves. The instruction covers title, body, reason and recommendation while protecting identifiers, paths, symbols, enums and quotations. Lane documents, PR descriptions and source text remain data, so their language does not choose explanatory output language. The minimal agentic contract now explicitly includes this locale requirement within structured-output instructions.

## Dead-lane coverage redispatch (2026-09-07)

The first production App review (bori#1744, rvw 0.13.0) took 41 minutes; four back-to-back 600 s barriers (discovery initial, discovery retry, coverage-redispatch, adjudication initial) were 2400.5 s of the 2474.6 s from job creation to check completion. `correctness` ended `exit_nonzero:124` at 600.13 / 600.08 / 600.14 s on its initial, retry, and coverage-redispatch attempts; `hygiene` ended at 104.9 s on an upstream "model is at capacity" error (`exit_nonzero:1`), then `exit_nonzero:124` at 600.09 and 600.16 s. `dynamic/goal-parity` died once at 600.06 s and recovered on retry at 571.2 s with eight findings; `contracts`, `security-exposure`, and `ci-integrity` completed first time in 188.9, 235.7, and 101.0 s. Same-day local bori runs at 600 s (pr-1771, pr-1675, pr-1769) reproduced the correctness/hygiene pattern, and one 1500 s run (pr-1758) still hit the cap, so the cause is the repository × lane × budget, not App infrastructure.

The previous coverage requirement mandated one redispatch for every incomplete lane, and a lane with zero valid runs is always incomplete, so a lane that had already died twice at the deadline was re-run a third time with the same prompt, no feedback, and the same cap: a guaranteed extra 600 s barrier. The rule now decides on final planned executions: a lane whose every final attempt is `exit_nonzero:124` and that has no VALID run is dead by timeout and is skipped with `redispatch_skipped: "dead_by_timeout"`. Earlier attempt reasons are ignored on purpose (hygiene's capacity error then 124 is dead), while two non-timeout failures (`exit_nonzero:1` twice) keep the original transient-recovery redispatch, and a lane that recovered on retry but omitted a hunk is redispatched as before. With the skip, dead-lane discovery costs 2D instead of 3D; a lane that returns valid-but-incomplete receipts on retry can still take 3D.

Attempt visibility followed from the same run. The RCA had to infer the third wave's outcome from `discover-runtime/coverage-redispatch/*/r1/usage.json` because `attempts[]` was built from initial and retry only and dropped `RunResult.wall_seconds`. Every attempt now records `wave` and `wall_seconds`, and a coverage-wave run is persisted on its lane as a `redispatch` attempt tagged `coverage_redispatch`. It is a separate list rather than a third entry in `runs[].attempts` because a planned row's final attempt must keep matching the row's status and the planned identity set must not change; a coverage-wave run is a different execution whose validity does not alter the planned row. Legacy attempt records without `wave` load as `initial` then `retry`, which is how they were built.

## Budget contract and tool-call telemetry (2026-09-08)

On the measured production run at a 900 s deadline, the three lanes that died were working, not hung. Each of the four retained dead-lane logs shows an interim assistant message listing every one of the 14 changed regions early, at 11%, 60%, 59%, and 23% of the log, followed by 86, 21, 23, and 29 further tool commands without the final schema ever being emitted. Valid lanes used 3 to 8 tool commands; the one lane that converged used 33 on its initial attempt and 7 on retry; dead lanes ran 41 to 95. The prompt never stated the wall budget (`prompts.py` had no mention of the deadline), so a longer deadline bought more exploration rather than earlier convergence. The shared output instructions therefore carry a budget paragraph whenever the dispatcher knows the deadline: the wall budget in seconds with the consequence of expiry, coverage of every changed region first, the final structured output immediately afterwards, exploration beyond the changed regions out of scope unless a finding's evidence requires it, and, for agentic prompts only, a tool-call budget of 40 as guidance plus the rule not to fetch, clone, or query remote repositories or APIs because base and head are local. Inline prompts run tool-less and receive only the time and coverage sentences. The paragraph sits between the schema rules and the locale contract as English instruction-layer prose like the rest of the output instructions; the locale contract is unchanged, and a prompt built without a deadline is byte-identical to before.

The tool-call and assistant-message counts are telemetry, not enforcement. The runtime counts the lines of `run.log` that are exactly `exec` and exactly `codex`, the item headers the Codex human output prints before each command and each assistant message, and records them on `usage.json`; discovery copies them onto each persisted attempt as `tool_calls` and `assistant_messages`, and legacy attempt records without them load with unknown counts. Tool output that itself contains such a bare line would over-count (an indented or prefixed occurrence does not match), which is acceptable for telemetry and is why the controller never kills or invalidates a run on the budget; the budget shortens tails without shrinking the reviewed surface because coverage comes first.

The runtime watchdog reason `no_output_after:<N>s` (design decision 3 of the `runtime-silence-and-budget` change) is transient rather than dead-by-timeout. A deadline kill means the lane used every second it was given and a third identical run is deterministic waste, whereas a watchdog kill means the runtime never engaged and a fresh process usually does. A watchdog-killed lane therefore keeps its ordinary retry and its single coverage-wave run; only `exit_nonzero:124` on every final planned execution marks death, so a watchdog kill followed by a deadline kill is dead and two watchdog kills are not.
