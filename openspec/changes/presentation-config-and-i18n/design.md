## Context

See proposal.md for motivation. The evidence base is `/tmp/rvw-publication-audit.md`, whose v0.11.5 and #70 citations were re-resolved against current main: base readers `registry.py:190,269`, diagnostic report `report.py:336`, coupled publication `publish.py:159`, shared summary `summary.py:265`, check create/update `github-app.ts:253,298`, and Worker titles/summary `review-job.ts:131,137`. `cloud/package.json` has no YAML dependency.

## Goals / Non-Goals

Goals: one anchored presentation snapshot; catalogs for chrome; a distinct concise publication view; deterministic locale checking backed by one bounded runtime rewrite. Non-goals: lane content or selection, replica/voting/policy thresholds, diagnostic data loss, release/deployment files, external registry mutation, or consumer-repository edits.

## Decisions

1. `PresentationConfig` is a strict Pydantic value, loaded alongside repository policy after target anchoring. It is persisted as `presentation.json` and exposed in process/summary. Worktree opt-in shares the existing non-SoT warning. Replay uses the saved object; missing old snapshots use defaults.
2. Python `i18n/catalog_ko.py`, `catalog_en.py`, and `t(key, locale, **kwargs)` provide all renderer chrome. The stage-two migration changes only string selection, preserving diagnostic content selection. Matching key sets and formatting contracts have deterministic tests; renderer Hangul scans prevent drift.
3. `render_publication` selects human content independently of `report.md`. Rule tags, anchors and verbatim evidence remain immutable; diagnostic IDs/votes/folds/budgets/build metadata stay in artifacts. Inline eligibility and two-call 422 behavior remain unchanged. Gate/stack use the same catalog and human view boundaries.
4. Worker bootstrap fetches base config before check creation. A small bounded YAML subset parser avoids adding a large parser dependency for four scalar fields. Unsupported/malformed content falls back to defaults with a recorded invalid reason; Python still validates authoritatively. Worker `i18n.ts` supplies all early and terminal chrome, and updates can rename checks from the Python snapshot. Machine diagnostics go into collapsed check text.
5. Locale contract is appended to shared output instructions and all ordinary/expanded/retry/stack-presence prompts. Diff, PR text and lane language cannot override it.
6. `langgate.py` segments rendered prose while protecting Markdown code, paths, identifiers, rules, anchors and evidence. It skips fewer than 12 letters, requires Hangul share >=0.6 for ko or Latin share >=0.9 with zero Hangul for en, and rejects uncertainty. Exactly one injected `Rewriter` call uses the existing runtime and accepts only same-count prose segments. Reassembly preserves immutable structure, and a second language/invariant check gates every publication route. Remaining mismatch uses failure code `publication_language_mismatch` and existing infrastructure exit 3; explicit CLI or auto-policy fallback records `language_fallback_used`.

## Risks / Trade-offs

- Mixed technical prose can fail the heuristic → remove known code/identifier tokens, skip short segments, and provide one bounded rewrite plus explicit recorded fallback.
- Rewriting can alter facts → expose only prose slots, require same-count output, compare immutable finding metadata and evidence fences, and preserve original diagnostic artifacts.
- Bootstrap subset may reject YAML accepted by Python → document its narrow grammar and always let the authoritative Python snapshot correct final branding; invalid bootstrap is retained as a diagnostic.
- Existing tests expect Korean defaults or raw report publication → migrate expectations to explicit locale snapshots and separate diagnostic/publication assertions.

## Migration Plan

Four staged conventional commits: config; catalogs without content-selection changes; human publication plus Worker integration; locale runtime enforcement. Each includes matching main specs/context and tests; all change deltas remain active and unarchived. Rollback is the reverse commit order; persisted legacy runs remain readable through defaults. No deployment or push is part of this work.
