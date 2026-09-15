## 1. Reduce the contract before implementation

- [x] 1.1 Restore both main spec.md files to origin/main, reduce proposal/design/deltas to PR-scoped trigger behavior, preserve baseline MODIFIED obligations, and document mention matching/precheck and policy lint warning.
- [x] 1.2 Update operator docs/context for PR-scoped evidence, same-PR joins, quote/boundary exclusions, cached identity, and replay pins.

## 2. Regression tests and implementation

- [x] 2.1 Remove the cross-PR coordinator, durable queue outbox, seeding/release/reconciliation code, new alarm roles, dead admit/restart helpers, and tests solely for removed paths; keep baseline executor provisioning/poll/cleanup/check-update behavior.
- [x] 2.2 Write failing production-entry regressions and implement same-PR/head completed evidence and check fallback, including another PR sharing the SHA, real serialized start joins/replays, and preservation of pending cleanup/check obligations across reinstantiation.
- [x] 2.3 Write failing webhook regressions for formatted boundaries, blockquotes, cached identity/precheck cost and failure handling; implement them with one parser per isolate and retain authorization, token fallback, reactions, and comment pin behavior.
- [x] 2.4 Give every valid shared parser fixture an exact normalized expected output in both runtimes; add warning-only policy lint and retain strict validation/defaults and legacy/new summary contracts.
- [x] 2.5 Preserve manifest subscriptions/Issues write and verify Wrangler declarations are unchanged; rerun the review matcher probes and confirmed mutation regressions against production paths.

## 3. Verification and handoff

- [x] 3.1 Independently inspect the diff and run every requested bare root/Worker gate, strict OpenSpec validation, and both delta parity checks at problems: 0; verify main spec.md files remain byte-identical to origin/main.
- [x] 3.2 Rewrite the unpushed branch to one conventional feature commit on origin/main, verify clean status and the one-commit shape, and write /tmp/rvw-trigger-fix-report.md with removal inventory, PR-scoping/probe/cost/parity evidence, gate exits, commit SHA, and open questions. Do not archive or deploy.

## 4. Fix round 2

- [x] 4.1 Update deltas/design/operator docs/context for authoritative requested-job check identity, slash-suffix rejection, and expiry-aware mention prechecks; keep main specifications and Wrangler declarations unchanged.
- [x] 4.2 Import the reviewer's signed-webhook PR-scope cases, observe contradictory-identity failures, and fix evidence matching against the requested job; commit association alone must fail open.
- [x] 4.3 Add a failing signed-webhook team-mention regression and reject slash suffixes while preserving punctuation, strikethrough, and curly-quoted mentions.
- [x] 4.4 Import the reviewer's rename-refresh regression, assert acceptance after cache expiry, observe its failure, and fix the stale precheck without losing no-at-sign or fresh-cache cost guarantees.
- [x] 4.5 Run all requested bare gates and both parity checks at problems: 0, rerun probe rows, and verify main spec.md files and Wrangler declarations match origin/main.
- [x] 4.6 Append red-to-green evidence, file references, probe/gate results, and amended SHA to the fix report; amend the single feature commit and verify clean status and one-commit shape without pushing, publishing, or archiving.
