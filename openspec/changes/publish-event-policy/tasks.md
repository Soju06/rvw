## 1. Read publish and thread policies from the repository auto policy

- [x] 1.1 Add failing tests: defaults reproduce today's behaviour; every valid `publish`/`threads` combination loads; `approve` without the opt-in is `approve_not_opted_in`; unknown values and keys are `publish_policy_invalid`; a missing file selects defaults; the base ref wins over the head; `run` exits 2 before review on an invalid block.
- [x] 1.2 Implement `PublishPolicy`, `ThreadPolicy`, `PublishPolicyInvalid`, `validate_policy`, `publish_policy_source`, the packaged default blocks, and the `run` failure-code mapping.
- [x] 1.3 Amend the lane-registry and operation-modes main specs and the lane-registry context, then commit feat(policy): read publish and thread policies from .rvw/policies/auto.yaml.

## 2. Fingerprint findings and reconcile rvw's own review threads

- [x] 2.1 Add failing tests: fingerprint stable under line shifts and whitespace, changed by evidence; marker round-trip; the language gate ignores HTML comments; reconciliation fixture (fixed, persisting, moved, outdated-continuing, ambiguous, resolved-by-author, lane-invalid, login-unknown) yields exact resolved/reused/superseded/posted/ambiguous/skipped sets; catalog parity and the Hangul guard cover `threads.py`.
- [x] 2.2 Implement `src/rvw/threads.py` (identity, normalize, fingerprint, markers, line mapping through diff hunks, compare-API provider, `reconcile_threads` with the fail-safe rules, GraphQL read/resolve/reply through the client seam), the markers on inline bodies, the rvw-marker exclusion in `langgate`, `PublishFacts` on the summary contract with the regenerated schema and Worker parser acceptance, and reconciliation inside `publish_review` after the review write.
- [x] 2.3 Amend the reporting main spec and context, then commit feat(reporting): fingerprint findings and reuse or resolve rvw's own review threads across heads.

## 3. Select the review event from policy, once per head, and dismiss on pass

- [x] 3.1 Add failing tests: BLOCK + `request_changes` posts REQUEST_CHANGES; PASS + opted-in `approve` posts APPROVE with body only when there is prose; PASS + `none` without prose posts nothing; degraded and language-fallback runs never escalate; `--event comment` downgrades and `--event request_changes` over a `comment` policy is rejected; a second REQUEST_CHANGES on the same head is skipped as `duplicate_review_same_head`; dismissal touches exactly rvw's own REQUEST_CHANGES and treats 422 as done; summary and payload carry the recorded fields.
- [x] 3.2 Implement event selection, `commit_id` pinning, the GitHub client seam (REST and GraphQL through `gh api`), own-login resolution (`RVW_GITHUB_LOGIN`, then `gh api user`), same-head idempotency, dismissal, `PublishFacts` on `ExecutionSummary` with the regenerated schema resource, the `policy.json` snapshot, `rvw publish --event`, and the `run`/`auto`/`review`/`gate` call sites.
- [x] 3.3 Amend the reporting, pr-gate, and operation-modes main specs and contexts, README, and container docs, then commit feat(reporting): select the review event from policy, idempotent per head, dismiss on pass.

## 4. Rename the App publish mode and surface publish and thread facts

- [x] 4.1 Add failing Vitest coverage: the argv uses `--publish github-review`; the contract parser accepts `github-comment` as an alias and the new summary fields; check facts carry `publish` and `publication_skipped`; the process env carries `RVW_GITHUB_LOGIN` when the check-run response names the App slug. Add Python tests for the CLI alias warning and normalization.
- [x] 4.2 Implement the Worker rename, alias, facts, slug capture, and env passing; the Python `--publish` alias with deprecation warning; regenerated `process.schema.json`; cloud and container docs.
- [x] 4.3 Amend the operation-modes main spec and context, then commit feat(cloud): rename the publish mode to github-review and surface publish and thread facts.
