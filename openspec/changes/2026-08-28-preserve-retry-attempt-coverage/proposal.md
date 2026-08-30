## Why

When an all-INVALID lane-chunk triggers the dispatcher's replacement wave, the
final result map keeps only the retry result per `(lane_id, replica, chunk)`.
Persisted discovery coverage therefore records only the retry's status and
`invalid_reason`; the initial wave's machine-readable failure causes (e.g.
`exit_nonzero:124`, `spawn_error:FileNotFoundError`) are lost even though PR
#16 preserved the initial artifacts on disk. Failures such as `spawn_error`
can leave an empty log and no output, making the original cause impossible to
reconstruct after a successful retry. Confirmed by rvw self-review on PR #16
(finding `c1476eb7`, parked as a follow-up).

## What Changes

- Run coverage records the ordered per-attempt status and invalid reason for
  every dispatched execution, while aggregate validity remains keyed on the
  final attempt.
- Persisted discovery artifacts include the attempt records; artifacts written
  before this change load with empty attempt history.
- Add deterministic regressions for retried-lane coverage, artifact
  round-trip, and legacy-artifact loading.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery`: Coverage preserves attempt-level status/reason across the
  all-invalid replacement wave.

## Impact

Affected implementation is `src/rvw/dispatch.py` (returning initial-wave
results alongside final results), `src/rvw/discover.py` (`RunCoverage`
attempt records), and `src/rvw/store.py` discover persistence, plus tests and
the discovery specification. Report rendering, adjudication, gate, stack
review, CLI options, and dependencies do not change.
