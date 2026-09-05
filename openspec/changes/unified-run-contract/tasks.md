## 1. Correctness regressions first

- [x] 1.1 Add and observe failing regressions for all-INVALID auto discovery and App zero-valid coverage.
- [x] 1.2 Add and observe failing DO regressions for timeout, process start failure, and supersession diagnostic persistence before destruction.
- [x] 1.3 Add and observe failing run/auto regressions for invalid policy/target and checkout, runtime, adjudication, and publication exceptions using the reserved exit matrix.
- [x] 1.4 Add and observe failing policy precedence/package fallback tests and PR-URL argv repository-binding tests.

## 2. Shared Python execution contract

- [x] 2.1 Install the packaged auto default, implement provenance-aware policy precedence, and warn on deprecated external fallback.
- [x] 2.2 Bind every PR-URL GitHub call to its repository and verify event base/head anchors before runtime dispatch.
- [x] 2.3 Implement `rvw run` with explicit output, publication, policy, and shared runtime options; reduce `auto` to compatibility argument translation.
- [x] 2.4 Initialize and finalize strict version-1 process contracts for success, BLOCK, invalid input, and infrastructure failure; preserve partial artifacts and fail closed on failed review summaries.
- [x] 2.5 Emit the shared summary, top-level redacted diagnostics, and sorted recursive manifest including accurate process self-size.
- [x] 2.6 Add golden schema/manifest tests, exit matrix coverage for both commands, and early-failure/anchor tests.

## 3. Thin adapters and packaging

- [x] 3.1 Change the App command to `rvw run` with webhook anchors and `/workspace/result`; remove TS repository binding, stdout/run-ID parsing, and stage copying.
- [x] 3.2 Consume Python process/summary artifacts and manifest; remove independent TS counts and hardcoded artifact-name exports; validate canonical Check mapping.
- [x] 3.3 Funnel every App terminal path through best-effort shared diagnostics before destruction and merge SDK-only supplements into the shared envelope.
- [x] 3.4 Change Actions to the anchored `run` invocation with a mounted output directory, runtime inputs, default 90-minute timeout, canonical result summary, and pinned artifact upload on all terminal outcomes.
- [x] 3.5 Consolidate the Codex template and GitHub CLI installation helper across both Dockerfiles and remove the cloud-only policy copy.

## 4. Parity and handoff verification

- [x] 4.1 Execute the offline three-adapter fixture smoke with fake gh/Codex and compare normalized process contracts, summaries, and full artifact manifests.
- [x] 4.2 Independently inspect implementation diffs and run all five bare Python/OpenSpec repository gates.
- [x] 4.3 Run strict change validation, actionlint, deployer-neutrality, cloud clean install/typecheck/tests, and the specified spike Wrangler dry-run.
- [x] 4.4 Build both Dockerfiles and remove the temporary verification image tags.
- [x] 4.5 Synchronize all six main specifications and adjacent contexts with implemented behavior and audit evidence; retain the active change for strict validation.
- [x] 4.6 Record deleted adapter blocks, schema, exit table, parity result, and any audit deferrals for the requested PR handoff.
