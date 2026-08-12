## Context

PR #16 made the replacement wave write to `lane_slug[/cN]/retry/rN`, so
initial artifacts survive on disk. But `dispatch` still returns only the
final result per identity key, and `RunCoverage` carries a single
`valid`/`invalid_reason` pair, so persisted coverage loses the initial
attempt's machine-readable failure reason. Doctor and operators triaging
"why did this lane retry" must reverse-engineer the initial cause from raw
artifact directories, which is impossible for spawn errors that leave empty
logs.

## Goals / Non-Goals

- Goal: every dispatched execution's attempt history (status + invalid
  reason, in execution order) survives into `discover.json`.
- Goal: legacy `discover.json` files (no attempt records) keep loading.
- Non-goal: changing retry semantics, wave counts, or directory layout.
- Non-goal: surfacing attempt history in the rendered report (doctor/JSON
  consumers first; report rendering can follow later if wanted).

## Decisions

### Coverage rows gain ordered attempt records

`RunCoverage` gains `attempts: list[RunAttempt]` where `RunAttempt` is a
strict model `{attempt: int >= 1, valid: bool, invalid_reason: str | None}`
with the same validity/reason invariant as the row itself. The row-level
`valid`/`invalid_reason`/`findings` keep their current meaning (final
attempt), so every existing consumer (doctor, report, gate plan) is
untouched. For non-retried runs `attempts` has one entry mirroring the row.

### Dispatch returns initial results alongside finals

`dispatch` currently folds `[*main_results, *retry_results]` into
`final_by_key` and discards the shadowed initial results. It will also expose
the initial-wave result per retried key (implementation detail left to the
executor: either a second return value or enriching the sort step), letting
`discover` build attempt lists without re-deriving retry membership. The
public single-list return shape used by callers stays available to avoid
touching sample/stack call sites.

### Persistence is additive and lenient on load

`save_discover` writes attempt records inside each coverage item.
`load_discover` treats a missing `attempts` key as an empty list, so runs
persisted before this change (and the current live registry) keep loading
without migration.

## Risks / Trade-offs

- `RunCoverage` is validated strictly; additive fields must default safely so
  legacy JSON round-trips. Mitigated by the lenient-load regression.
- Slightly larger `discover.json`; negligible (two small fields per run).
