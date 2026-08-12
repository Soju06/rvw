# Discovery context

## Purpose and scope

DISCOVER resolves active lanes into bounded runtime work, supplies each lane the right diff and intent context, and enriches only valid runtime output. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- ADR-005 makes `unscoped-sweep` the structural coverage net. On a six-defect fixture, the scoped slop lane found 0/3 deep defects in both enum and free-ID conditions, while the sweep found 3/3. Its warning cap contains the higher expected false-positive rate.
- ADR-006 measured the benefit of three replicas. Eight repeated runs showed an individual run recovered about 88% of the union; three replicas raised expected union recall to about 99%, while four added little. The 2026-07-30 owner decision keeps that as opt-in heavy verification and makes one replica the ordinary default to avoid executor overload across concurrent rvw runs.
- Concurrency tests on a 22-core host found N=4, 8, and 16 completed in 49.1, 50.0, and 50.6 seconds. After concurrent rvw processes saturated the shared account pool on 2026-08-06, the default cap was reduced to 8 while retaining an explicit positive override, one wave, and heavy-first LPT ordering.
- 2026-08-12: Replacement-wave directory reuse reproduced destruction of initial INVALID evidence, motivating distinct `retry/` artifact directories.
- 2026-08-12: PR #16 self-review finding `c1476eb7` confirmed that retry discarded the initial `invalid_reason`, motivating persisted ordered attempt coverage.
- A real one-chunk PR #1119 run dispatched 13 lanes x 3 replicas and completed DISCOVER in about 410 seconds with all 39 runs valid. ADJUDICATE then took about 197 seconds.
- The same PR contained a 2.84 MB generated `contract-graph.json` inside a 2.87 MB diff. Excluding it left 26,195 characters of reviewable source and motivated visible, file-level diff budgeting.
- On 2026-07-28, three `apifuse-provider-tabelog` worktree reviews retained 734,985 characters and `codex-lb` PR #1520 retained 464,425 characters. Both were legitimate source review units, so the 400,000-character aggregate limit now bounds one prompt and expands work into ordered whole-file chunks instead of rejecting the review.

## Constraints

- The code does not hardcode `unscoped-sweep`; its mandatory status depends on the external default registry keeping it in a predicate-free base layer.
- The covered-rules section is prompt guidance. The strict schema prevents foreign IDs but cannot prove the model avoided semantically duplicate findings.
- The default per-file and per-chunk limits are characters, not tokens or bytes.
- Cross-chunk prompts list all kept paths and mark the current subset, but do not duplicate other chunks' source text.
- Concurrency above 16 has not been measured; operators who override the default 8 are responsible for matching shared gateway capacity.
- PR fallback uses title and body; linked issues from ADR-010 are not resolved by the current target model.

## Failure modes

- A base registry missing `unscoped-sweep` creates a silent coverage gap.
- A generated file not matched by the default globs may create extra chunks and model work.
- If all replicas remain invalid after the replacement wave, the lane contributes no findings but remains visible with zero valid coverage.
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
