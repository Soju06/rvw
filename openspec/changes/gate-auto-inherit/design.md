## Context

Explicit inheritance already has hardened run-ID lookup, pinned artifact reads, source identity validation, tiered matching, summary generation, and verdict provenance. The missing behavior is source selection for fresh target mode. See `proposal.md` for motivation.

## Goals / Non-Goals

**Goals:**

- Select only prior completed same-PR gate evidence with recorded dispositions.
- Feed an automatically selected run ID into the existing explicit-inheritance path.
- Keep absent history nonfatal and make selection or absence visible to operators.

**Non-Goals:**

- Automatic inheritance during resume, commit, or uncommitted review modes.
- Relaxing explicit inheritance validation or reading the external review registry.
- Inferring dispositions from pause templates or incomplete verdicts.

## Decisions

### Discover after resolving the target and allocating the current run

Fresh target mode needs canonical repository and PR identity, and the newly allocated ID must be explicitly excluded. Discovery will scan direct child run IDs under `out_root`, order timestamped IDs newest-first, and probe candidate artifacts without following symlinks. Performing discovery before target resolution was rejected because repository identity would remain ambiguous.

### Qualify with persisted target and completed verdict dispositions

A candidate qualifies only when its target is a PR for the case-insensitive same repository and exact PR number and its gate verdict is completed with disposition finding records. Pause/failure verdicts and empty/no-verdict runs do not represent recorded dispositions. Reusing mere template YAML was rejected because it has not crossed the existing validation boundary.

### Reuse the explicit source variable and load path

After selection, the command assigns the chosen ID to the same effective inheritance input consumed by `_load_inherited_dispositions`, matching, summaries, and artifacts. A parallel auto-inheritance matcher was rejected because it would duplicate security and provenance logic.

### Treat candidate corruption as nonqualification during scanning

Automatic discovery is best-effort: unreadable, malformed, symlinked, or identity-mismatched candidates are skipped while scanning continues. Once selected, the ordinary explicit loader revalidates the source and remains fail-closed. This preserves fail-open absence without weakening the trusted source boundary.

## Risks / Trade-offs

- [Directory order differs from chronological order] → Parse and compare the timestamp-bearing run IDs rather than relying on filesystem iteration or modification time.
- [A malformed newer candidate hides valid history] → Skip nonqualifying probes and continue through all candidates.
- [Selection races with artifact replacement] → Treat discovery as untrusted selection only, then reopen and validate through the existing pinned loader before use.
- [Large run roots add startup work] → Read only the minimal target and verdict artifacts and stop after the newest qualifying candidate.

## Migration Plan

Ship auto-discovery enabled for fresh PR target mode with `--no-inherit` as the deterministic escape hatch. No artifact schema migration is required because selected sources use existing provenance fields and summary artifacts.
