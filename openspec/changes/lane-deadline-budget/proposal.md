## Why

The first production App review (bori#1744, rvw 0.13.0, 2026-09-07) took 41 minutes. Four back-to-back 600-second barriers were 97% of wall clock: discovery initial, discovery retry, discovery coverage-redispatch, and adjudication initial. The `correctness` lane died at the deadline on all three attempts and `hygiene` on two, so the coverage-redispatch wave re-ran two lanes that already had zero valid runs with the same prompt, no feedback, and the same cap, a deterministic 600 seconds of waste. The App passed no `--deadline`, so the CLI default applied, and the check surfaced neither the failed lanes nor the phase that consumed the time. Same-day local bori runs at 600 seconds show the identical pattern.

## What Changes

- Coverage-redispatch skips lanes that are dead by timeout (every final planned execution ended in `exit_nonzero:124`) and records the skip as `redispatch_skipped: "dead_by_timeout"`; lanes failing for other reasons or with valid-but-incomplete runs keep one redispatch.
- Discovery attempts record `wave` (`initial | retry | coverage_redispatch`) and `wall_seconds`; coverage-wave results appear in `discover.json` as a dedicated `redispatch` attempt list per lane; adjudication outcomes record per-wave wall time.
- `summary.json` exposes `failed_lanes` (lane id and final reason), `wave_wall_seconds` per pipeline wave, and `lanes.uncovered_regions` beside the lane-hunk receipt count.
- The App passes `--deadline` explicitly from Worker var `RVW_REVIEW_DEADLINE_SECONDS` (default 900) and fails closed at config load unless `RVW_JOB_DEADLINE_MINUTES * 60 >= 5 * RVW_REVIEW_DEADLINE_SECONDS + 600`; committed job deadlines become 120 minutes.
- The localized publication summary names unfinished rule sets; the check `text` carries failed lanes, per-wave wall seconds, `lane_hunk_receipts`, and `uncovered_regions`; the language gate treats named lane identifiers as protected tokens.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: dead-lane redispatch rule, attempt `wave`/`wall_seconds`, redispatch visibility.
- `runtime-contract`: summary `failed_lanes`, per-wave wall fields, adjudication wave telemetry.
- `cloud-app-platform`: explicit `--deadline` var, job-cap coherence check, README table.
- `reporting`: failed-lanes sentence, check `text` facts, `uncovered_regions` versus `lane_hunk_receipts`, protected lane identifiers in the language gate.

## Impact

Python discovery, adjudication outcome telemetry, summary contract and schema resource, publication catalogs and language gate; Worker config, invocation, contract parser, and check text; Wrangler vars; cloud README; deterministic Python and Vitest tests. No lane content, replica counts, adjudication semantics, policy thresholds, retry-with-feedback behavior, CLI deadline defaults or ceilings, container classes, Terraform, workflows, or release notes change.
