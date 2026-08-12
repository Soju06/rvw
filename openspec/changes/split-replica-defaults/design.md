## Context

The common pipeline currently accepts one `replicas` value and forwards it to both model stages. CLI plan payloads likewise expose one count, although coverage artifacts describe only discovery dispatches. See `proposal.md` for the measured motivation and the delta specs for the new contract.

## Goals / Non-Goals

**Goals:**

- Make the stage-specific count explicit at every Python, CLI, stack, and gate-plan boundary.
- Preserve the existing `replicas` JSON meaning and discovery coverage calculation for compatibility.
- Keep explicit one-replica adjudication available and all execution algorithms unchanged.

**Non-Goals:**

- Changing discovery concurrency, retry waves, adjudication widening, vote thresholds, deadlines, or sample behavior.
- Adding migration aliases for the removed public pipeline argument.

## Decisions

### Split at the common pipeline boundary

`run_pipeline` will require `discover_replicas` and `adjudicate_replicas` and validate both before stage execution. This makes accidental coupling a type-visible call-site failure. Retaining a deprecated combined argument was rejected because it leaves ambiguous precedence and contradicts the requested removal.

### Preserve `replicas` as the discovery plan field

CLI plans and gate plans will add `adjudicate_replicas` while leaving `replicas` and all total-run arithmetic tied to discovery. Renaming the existing field was rejected because downstream readers could silently treat adjudication work as lane coverage.

### Put defaults at public declaration boundaries

Discovery stays at one and adjudication changes to three in their public callables and Typer options. Stack orchestration forwards both values rather than owning alternate defaults. This prevents wrappers from relying on incidental downstream defaults.

## Risks / Trade-offs

- [A missed wrapper continues coupling stages] → Add signature/default and CLI regression tests at every exposed boundary and use type checking to find stale call sites.
- [Downstream plan consumers reject an additional field] → Extend the payload without renaming or changing the established `replicas` field.
- [Three adjudicators consume more tokens] → Preserve `--adjudicate-replicas 1` as an explicit positive override.

## Migration Plan

Update all repository call sites in one change, synchronize main specs/context, and verify with the full offline gate set. External Python callers must replace `replicas=N` with the two explicit stage arguments; CLI callers retain the old discovery meaning and gain the new adjudication option.
