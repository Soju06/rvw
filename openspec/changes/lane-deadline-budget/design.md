## Context

See proposal.md for motivation. The evidence base is the artifact-grounded RCA of bori#1744 (`/tmp/rvw-1744-perf.md`, job artifacts under `/tmp/rvw-1744-artifacts/`), summarized in the discovery, cloud-app-platform, reporting, and runtime-contract `context.md` files. Sites re-resolved against 0.14.0 (`833956f`): redispatch selection `discover.py:338-360`, attempt persistence `discover.py:48-77, 223-236`, App argv `sandbox-auth.ts:134-141`, job deadline `review-job-contract.ts:53-57` and `wrangler.jsonc`, check facts `review-job.ts:152-161`, human summary `publication.py:43-57` and `summary.py:284-291`.

## Goals / Non-Goals

Goals: remove the deterministic third discovery barrier for dead lanes; make every wave's wall time and the redispatch wave visible in artifacts and the check; give the App an explicit, operator-tunable review deadline whose job cap is provably sufficient; name unfinished rule sets in the human summary. Non-goals: lane content, replica counts, adjudication semantics, `auto.yaml` thresholds, retry-with-feedback behavior, `DEFAULT_DEADLINE_SECONDS`/`MAX_DEADLINE_SECONDS`, container class or instance counts, Terraform, workflows, release notes.

## Decisions

1. Dead-by-timeout is decided on final planned executions: zero VALID and every final attempt `exit_nonzero:124`. Earlier attempt reasons do not matter, so `hygiene` (capacity error, then 124) is dead, while `exit_nonzero:1` twice is not and keeps the original transient-failure recovery redispatch. The skip is recorded as `LaneCoverage.redispatch_skipped`, never silent.
2. Redispatch results live in a dedicated `LaneCoverage.redispatch` list of `RunAttempt` tagged `wave: "coverage_redispatch"`, not inside `runs[].attempts`. Planned rows must keep "final attempt matches row status" and the planned identity set; a coverage-wave run is a separate execution whose validity does not change the planned row.
3. `RunAttempt.wave` is required in the model; a before-validator derives it from the attempt number (1 is initial, later are retry) only for legacy artifacts without the field, so old `discover.json` files still load. `wall_seconds` is optional and copied from `RunResult.wall_seconds`.
4. Adjudication wall time is recorded on `AdjudicationOutcome.wave_wall_seconds` keyed by the existing artifact labels (`initial`, `initial-retry`, `expanded`, `expanded-retry`) with the max replica wall. This is telemetry appended with a default, so `outcome.json` keeps loading; adjudication votes and retries are unchanged.
5. `summary.json` gains `failed_lanes` (lane id plus final normalized reason, joined in run order when executions differ), `wave_wall_seconds` for seven waves (five named in the owner decision plus the two adjudication retries that complete the 9D worst case), and `lanes.uncovered_regions`. `lanes.uncovered` keeps its lane-hunk receipt meaning; the Worker labels it `lane_hunk_receipts` in check text.
6. The Worker reads `RVW_REVIEW_DEADLINE_SECONDS` (integer 1..1800, the CLI ceiling) and validates `RVW_JOB_DEADLINE_MINUTES * 60 >= 5 * D + 600` in `requiredConfig`, so every request and queue batch fails closed with `config_incoherent` before any job starts. 900 is the committed default: 600 was at cap for `correctness`/`hygiene` in four of five completed same-day bori runs (the fifth at 96%/94% of cap), 1500 recovered #1692 but not #1697, and 900 keeps the no-retry path at 30 minutes with the dead-lane skip in place. 120 minutes satisfies the check with slack (minimum 85).
7. The language gate treats failed lane identifiers as protected literals in the check itself, not only in the rewrite path. Lane ids such as `correctness` are identifiers, not prose; without protection a Korean summary naming several lanes would fail the Hangul-share threshold on exactly the degraded runs it describes.

## Risks / Trade-offs

- A lane that would have recovered on a third identical attempt is no longer retried → the measured timeout is deterministic on bori; the skip is recorded and the operator can raise the deadline var instead.
- Strict Worker parsing rejects summaries with unknown fields → the parser accepts the new fields as optional so the same release deploys Python and Worker together while fixtures without them still parse.
- A deployer overriding `RVW_JOB_DEADLINE_MINUTES` below the budget → fails closed with a machine-readable reason at config load; the reusable workflow default is raised to 120 alongside the committed value so a caller that omits the input does not overlay a lower cap.

## Migration Plan

Four staged conventional commits on one branch: dead-lane skip; attempt wave/wall and failed lanes; explicit App deadline and coherence check; check-text and summary sentence. Each stage updates main specs and context. Legacy `discover.json`, `outcome.json`, and `summary.json` load with defaults. No deployment, push, or PR is part of this work; the change stays unarchived.
