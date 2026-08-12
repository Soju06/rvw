## Why

The shared one-replica default makes adjudication a single-vote rubber stamp: 250 of 272 measured production groups were confirmed, while adjudication contributes little critical-path concurrency compared with discovery. Discovery must remain cheap by default, but adjudication should restore independent majority evidence.

## What Changes

- **BREAKING**: Replace the common pipeline's combined `replicas` argument with separately validated `discover_replicas` and `adjudicate_replicas` arguments.
- Keep discovery and `--replicas` defaults at one while changing adjudication defaults to three, including stack review.
- Add `--adjudicate-replicas` to review, gate, auto, plan, and stack review, and record both values in plan artifacts while preserving `replicas` as the discovery count.
- Keep coverage validation tied to discovery replicas and leave voting, retry, widening, semaphore, and deadline behavior unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `adjudication`: Restore three-replica majority adjudication as the default while retaining explicit single-vote mode.
- `discovery`: Clarify that the unchanged one-replica count is independent from adjudication replication.
- `operation-modes`: Split routine command and plan replica controls and defaults.
- `pr-gate`: Split gate plan and pipeline replication while keeping coverage keyed to discovery replicas.

## Impact

The public Python call signatures in `pipeline.py` and `adjudicate.py`, Typer command options in `cli.py`, stack orchestration, gate plan JSON, and declaration-boundary tests change. Existing plan consumers keep reading `replicas` as discovery count and may opt into the new `adjudicate_replicas` field. No dependency, registry, merge, report, publication, or sampling behavior changes.
