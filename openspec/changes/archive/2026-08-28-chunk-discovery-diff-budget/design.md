## Context

`apply_diff_budget()` currently filters whole-file segments and then rejects when their aggregate exceeds 400,000 characters. Discovery, dispatch retry/deduplication, artifacts, coverage, gate plans, sampling, and CLI planning all assume only lane and replica axes. The approved behavior turns the aggregate limit into a per-prompt limit while retaining generated/oversized exclusion and exact fail-closed accounting.

## Goals / Non-Goals

**Goals:**

- Partition every kept file exactly once using deterministic, input-order next-fit chunks bounded by the configured aggregate character limit.
- Execute and account for every lane-replica-chunk combination, with useful cross-chunk prompt context.
- Preserve existing one-chunk diff bytes and runtime artifact paths.
- Make sampling and planning use the same chunk planner as discovery.
- Keep finding identity and replica agreement independent of chunk placement.

**Non-Goals:**

- Splitting a single file or hunk across prompts.
- Reordering files to minimize chunk count.
- Changing generated globs, the 200,000-character file exclusion, merge keys, or the external registry.
- Supporting legacy `DiffBudgetExceeded` imports or old persisted strict schemas.

## Decisions

### Return explicit chunks and placement accounting

`apply_diff_budget()` returns `list[DiffChunk]` plus `DiffBudgetReport`. Each chunk carries its one-based index, ordered files, complete filtered diff text, and kept-segment character count. The report retains existing totals and adds `chunk_count` and ordered placement records without duplicating diff text. An all-excluded diff still produces one logical chunk so planning cannot become vacuous.

The planner uses contiguous next-fit packing: append the next complete file segment when it fits; otherwise close the current chunk and start the next. This is the required order-preserving greedy behavior and makes output deterministic. Configuration requires `max_file_chars <= max_total_chars`, ensuring every retained segment fits one chunk. First-fit or size sorting was rejected because either revisits older bins or changes review order.

The existing exclusion header is attached to each chunk for visibility but is outside kept-segment accounting, as it is today. In the one-chunk case the returned text is byte-identical to the former filtered diff.

### Treat chunk as a first-class dispatch and artifact axis

`PlannedRun` and `RunResult` carry one-based chunk identity. Dispatch deduplication, sorting, and all-invalid retry group by `(lane, chunk)` and preserve replica semantics within that group. One-chunk artifacts remain `<lane-slug>/r<replica>/`; multi-chunk artifacts use `<lane-slug>/c<chunk>/r<replica>/`, leaving `r<replica>` last for the Codex adapter. Sampling applies the same conditional path beneath each enum/free variant.

Every prompt gets a generated chunk context section containing `chunk k/N` and the complete ordered kept-file list, with current-chunk files explicitly marked. Only the chunk diff is placed in the unified-diff section.

### Preserve lane summaries while persisting exact run coverage

Each lane coverage row retains aggregate `dispatched`, `valid`, and `findings` values and adds strict run records for every `(replica, chunk)`, including boolean validity, finding count, and a machine-readable invalid reason when invalid. Model validation enforces aggregate consistency and unique run identities.

Gate plans persist `chunk_count`. Gate validation constructs the full Cartesian product of planned lanes, replicas, and chunks, requires exact equality with persisted coverage run identities, and requires every record valid. Aggregate equality alone is insufficient and is checked only as an additional invariant.

### Keep finding and agreement identity unchanged

Discovery continues to enrich hunks from the full original diff. Chunk is execution provenance, not part of `EnrichedFinding`; merge remains keyed by `(file, hunk_id, rule_id)`, and agreement remains the count of distinct replica numbers. A regression test compares merge keys across different valid chunk plans.

### Share planning across discovery, sample, and CLI plan

Discovery, sampling, `rvw plan`, and gate-plan creation all call `apply_diff_budget()`. Sampling dispatches enum/free x replica x chunk and unions valid outputs as before. `rvw plan` exposes `chunk_count` and computes `total_runs = lanes x replicas x chunks` from the actual target diff.

## Risks / Trade-offs

- [More model calls and cost for large diffs] → The 400,000-character bound remains a quality budget, and plan output exposes the expanded run count before execution.
- [Cross-file reasoning weakens at chunk boundaries] → Every prompt lists all kept paths and marks the current subset; files remain whole and ordered.
- [Malformed or incomplete persisted coverage could appear numerically complete] → Strict nested run identities and Cartesian-product gate comparison reject duplicates, omissions, and invalid chunks.
- [Multi-chunk retry could overwrite artifacts] → Chunk directories are explicit and final result keys include chunk.
- [Schema changes reject older artifacts] → This is an intentional internal breaking change; there are no external consumers and no compatibility alias is retained.

## Migration Plan

1. Add failing planner, prompt, dispatch, coverage, stable-ID, sampling, plan, and persistence tests.
2. Implement chunk models and fanout, then update strict artifacts and reports.
3. Synchronize main specs/context and run all repository gates.
4. Keep the change active for controller review; archive only after verification and explicit follow-up.

Rollback is a source revert before release. Runtime registry data requires no migration.

## Open Questions

None. The owner-approved behavior fixes the packing order, limits, fanout, compatibility boundary, and fail-closed policy.
