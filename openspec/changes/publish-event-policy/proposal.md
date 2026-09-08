## Why

rvw hardcodes `event: COMMENT` for every GitHub review it publishes and never touches a thread it created. On a consuming repository whose `main` ruleset requires one approving review, code-owner review, `required_review_thread_resolution: true`, `dismiss_stale_reviews_on_push: true`, `require_last_push_approval: true`, and three unrelated required status checks, a COMMENT review is invisible to the merge gate, the rvw check run is not a required check, and the only merge-visible effect of a review is that every inline thread must be resolved by hand before merge. Each new head posts a fresh set of inline threads for findings that were already open, and a finding the author fixed stays open until someone clicks. The owner decided (2026-09-08) that the review event, the condition that selects it, and the way a REQUEST_CHANGES is undone are organisation policy that belongs in the consuming repository, and that rvw's own inline threads must behave as living threads: resolved automatically when the finding is gone on the next head, never duplicated while the finding persists.

## What Changes

- `.rvw/policies/auto.yaml` gains strict `publish` and `threads` blocks read at the base ref: `on_block: comment|request_changes`, `on_pass: comment|approve|none`, `dismiss_on_pass`, `approve_requires_explicit_opt_in` (default true, so `approve` is double-gated), `resolve_on_fix`, `reuse_open_thread`. Defaults reproduce today's COMMENT-only behaviour byte for byte; an unknown value fails closed with `publish_policy_invalid` before review starts.
- Every published inline comment ends with an invisible marker `<!-- rvw:v1 fp=<fingerprint> rule=<rule_id> lane=<lane_id> -->`. The fingerprint is the first 16 hex digits of SHA-256 over `rule_id`, path, and whitespace-, punctuation-, and line-number-normalized evidence; line numbers are not part of it.
- On a new head rvw reads its own open review threads through GraphQL, matches them to the new findings by fingerprint, then by `rule_id + path` with the original line mapped through the diff between the two heads, resolves threads whose finding is gone only when the finding's lane was valid on the new head, reuses open threads instead of posting duplicates, supersedes outdated threads whose finding continues at a mapped line, and leaves ambiguous groups untouched.
- The review event is selected from the policy verdict: BLOCK follows `on_block`, PASS follows `on_pass`; degraded, language-mismatch, and no-prose outcomes never escalate beyond COMMENT; `on_pass: none` publishes no review when there is nothing to show. A second REQUEST_CHANGES for the same head is never posted. A PASS with `dismiss_on_pass` dismisses rvw's own earlier REQUEST_CHANGES reviews with a catalog message. `rvw publish --event comment` downgrades only.
- `summary.json` and the App check facts record `publish.event`, `publish.policy_source`, `publish.actor`, `publication_skipped`, `dismissed_review_ids`, `resolved_thread_ids`, `reused_thread_ids`, `superseded_thread_ids`, `threads_ambiguous`, and `threads_skipped_lane_invalid`.
- The App publish mode is renamed `github-review`; `github-comment` remains an accepted alias for one release with a deprecation warning. The Worker passes the App's bot login to the review process so Python can filter threads and reviews to its own author; the Worker does not choose the event.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `reporting`: policy-selected review event with COMMENT default, finding fingerprint and marker, thread reuse and resolution with four fail-safe rules, same-head idempotency, dismiss semantics, recorded publication fields, language gate ignoring HTML comments, dry-run as read-only planning.
- `pr-gate`: gate publication follows the same policy-selected event instead of hardcoded COMMENT.
- `operation-modes`: `--event` downgrade-only on `rvw publish`, publish mode rename and alias, approval expressible only through the double-gated repository policy.
- `lane-registry`: `publish` and `threads` blocks of the repository auto policy are read at the base ref through the existing reader boundary.

## Impact

Python: `policy.py`, new `threads.py`, `publish.py`, `langgate.py`, `summary.py` and the summary schema resource, `cli.py` (`run`, `auto`, `review`, `gate`, `publish`), both i18n catalogs, README and container docs. Worker: `sandbox-auth.ts`, `review-job.ts`, `review-job-contract.ts`, `github-app.ts`, README. Tests in both trees. No change to PASS/BLOCK evaluation, severities, adjudication, discovery, prompts, runtimes, deadlines, lane content, the `.rvw/config.yaml` schema, publication prose beyond the invisible marker, Terraform, workflows, or release notes.
