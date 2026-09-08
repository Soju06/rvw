## 1. Skip coverage-redispatch for lanes dead by timeout

- [x] 1.1 Add failing discovery tests: 124 twice skips the third run and records the skip; `exit_nonzero:1` twice still redispatches once; 124 then valid-incomplete redispatches; capacity error then 124 skips.
- [x] 1.2 Implement `dead_by_timeout` on final planned executions and `LaneCoverage.redispatch_skipped`; keep every other redispatch path unchanged.
- [x] 1.3 Amend the discovery main spec and context, then commit feat(discovery): skip coverage-redispatch for lanes dead by timeout.

## 2. Record attempt wave and wall time, expose failed lanes

- [ ] 2.1 Add failing tests for `RunAttempt.wave`/`wall_seconds`, legacy attempt loading, the `LaneCoverage.redispatch` list, adjudication `wave_wall_seconds`, and summary `failed_lanes`/`wave_wall_seconds`.
- [ ] 2.2 Implement attempt wave/wall persistence, redispatch attempts, adjudication wave telemetry, summary fields, the regenerated summary schema resource, and Worker parser acceptance of the new summary fields.
- [ ] 2.3 Amend discovery and runtime-contract main specs and context, then commit feat(discovery): record attempt wave and wall time, expose failed lanes.

## 3. Pass an explicit review deadline and check job-cap coherence

- [ ] 3.1 Add failing Vitest coverage for `RVW_REVIEW_DEADLINE_SECONDS` parsing, the coherence check, and `--deadline` in the built argv; add Python tests that the entrypoint forwards `--deadline` and `process.json` records it.
- [ ] 3.2 Implement config parsing and fail-closed coherence, explicit `--deadline` in the invocation, Wrangler vars (900 / 120 for dev, spike, prod), regenerated Worker types, and the README env table.
- [ ] 3.3 Amend the cloud-app-platform main spec and context, then commit feat(cloud): pass an explicit review deadline and check job-cap coherence.

## 4. Name unfinished rule sets and the slowest phase in the check

- [ ] 4.1 Add failing tests for the ko/en failed-lanes sentence, catalog parity, protected lane identifiers in the language gate, `lanes.uncovered_regions`, and check text carrying `failed_lanes`, `wave_wall_seconds`, `lane_hunk_receipts`, and `uncovered_regions`; add the bori#1744 replay fixture test.
- [ ] 4.2 Implement the catalog keys, `publication_summary` sentence, gate protection, `uncovered_regions`, and Worker check text.
- [ ] 4.3 Amend reporting and cloud-app-platform main specs and context, then commit feat(reporting): name unfinished rule sets and the slowest phase in the check.
