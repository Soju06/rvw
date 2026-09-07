## Why

GitHub reviews currently mix human findings with execution diagnostics, repeat fixed branding, and combine Korean headings with model prose in an uncontrolled language. Base-ref presentation configuration, explicit catalogs, and a separate checked publication view make reviews readable while preserving diagnostic evidence.

## What Changes

- Resolve strict `.rvw/config.yaml` from the anchored base, persist its snapshot, and share it with every adapter.
- Move Python renderer and Worker chrome into matching Korean and English catalogs.
- Render concise review, inline, gate, and stack publication prose separately from diagnostic reports; move check diagnostics into `text`.
- Bootstrap App check branding from base-ref config and permit final check renaming.
- Enforce configured explanatory language in all model prompts and through one bounded, invariant-preserving publication rewrite; fail closed unless explicitly allowed to fall back.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `lane-registry`: base-ref presentation schema, defaults, and invalid-input boundary.
- `reporting`: persisted presentation, catalog contract, human publication, diagnostics, language gate.
- `pr-gate`: localized artifact-derived gate publication.
- `discovery`: locale contract including minimal agentic and retry prompts.
- `adjudication`: locale contract in ordinary, expanded, retry, and stack presence prompts.
- `cloud-app-platform`: bootstrap config, check name/title/summary/text, Worker catalogs.
- `operation-modes`: fallback flag/policy and language-failure exit.
- `runtime-contract`: persisted presentation and publication outcome contract.

## Impact

Python registry, run store, shared summaries, prompts, publication and CLI; Worker GitHub adapter and lifecycle; deterministic Python and Vitest tests. Diagnostic report and JSON structures remain evidence sources. No lane semantics, external registry, deployment configuration, release notes, or consuming-repository changes are included.
