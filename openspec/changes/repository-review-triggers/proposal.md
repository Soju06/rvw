## Problem

The Worker currently reviews every non-draft pull request and hardcodes draft eligibility. Generated release pull requests therefore trigger repeated reviews for every bot push. Repository conventions must be able to select which pull requests receive review.

## Outcome

Add a strict, base-ref anchored `triggers` block to `.rvw/policies/auto.yaml`. Python and the Worker parse and evaluate the same policy. Matching pull requests are skipped before discovery/enqueueing, with machine-readable trigger facts; explicit human reruns (`check_run.rerequested` and CLI `--force-review`) bypass the filter.

## Scope

- Strict Pydantic and Worker policy parsing and matching.
- Worker pre-enqueue filtering and neutral skipped checks.
- CLI filtering for PR targets and force bypass.
- Summary/check contract facts and fixtures.
- OpenSpec, operator documentation, and packaged defaults.

## Non-goals

Diff inspection, external registry changes, publication policy changes, and changes to the sibling publication-owned modules.
