## 1. Anchored presentation configuration

- [x] 1.1 Add failing regression tests for strict schema/defaults, base versus head/worktree resolution, malformed fail-closed behavior and replay snapshots.
- [x] 1.2 Implement PresentationConfig, shared base-ref loader, post-anchor resolution, presentation.json persistence, and shared process/summary exposure.
- [x] 1.3 Synchronize lane-registry main spec/context, verify stage tests, and commit feat(config): read .rvw/config.yaml at the base ref.

## 2. Locale catalogs without content-selection changes

- [x] 2.1 Introduce Python ko/en catalogs and t(), migrate all report/publish/gate/stack renderer chrome while preserving diagnostic content selection.
- [x] 2.2 Introduce Worker ko/en catalogs and migrate existing early/final chrome without changing content selection.
- [x] 2.3 Add Python formatting/key parity and Hangul-literal guards plus Vitest parity coverage; synchronize catalog specs/context, verify, and commit feat(i18n): move renderer and Worker chrome into ko/en catalogs.

## 3. Human publication and App check presentation

- [ ] 3.1 Add failing mixed-outcome fixture tests covering blocker/warnings/rejected/uncertain/uncovered selection in both locales and retained/dropped metadata.
- [ ] 3.2 Implement render_publication and inline/fallback human bodies; wire publish/run/auto, gate and stack using persisted presentation without changing diagnostic reports.
- [ ] 3.3 Add Worker base-ref bootstrap config parsing, check renaming, localized title/summary and collapsed structured text; verify malformed and all neutral terminal paths.
- [ ] 3.4 Synchronize reporting/pr-gate/cloud-app-platform main specs/context, verify stage tests and commit feat(reporting): publish a human publication view separate from report.md.

## 4. Hard model-language output contract

- [ ] 4.1 Add failing tests for locale instructions in all discovery/agentic/coverage/retry and ordinary/expanded/retry/stack-presence prompt variants, then thread the snapshot locale through them.
- [ ] 4.2 Add deterministic langgate segmentation/threshold tests and fake-Rewriter tests for exactly one rewrite, same-count output, immutable findings/anchors/rules/evidence, and final mismatch.
- [ ] 4.3 Implement langgate with bounded existing runtime adapter and wire before every publication route; add --allow-language-fallback and strict auto policy opt-in, recorded failure/fallback facts and exit 3 semantics.
- [ ] 4.4 Synchronize discovery/adjudication/reporting/operation-modes/runtime-contract main specs/context and commit feat(runtime): enforce the configured locale on model prose after verification.

## 5. Final verification and handoff

- [ ] 5.1 Run every requested bare Python, OpenSpec, cloud and literal-scan gate, fixing all failures.
- [ ] 5.2 Write /tmp/rvw-i18n-report.md within 160 lines with stage commits, resolution sites, catalog counts/tests, publication table, language contract, exact gate results, audit exclusions and git state; leave change unarchived and do not push or open a PR.
