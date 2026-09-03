## 1. OpenSpec contract

- [x] 1.1 Add strict cloud-app-platform and release-automation deltas covering webhook authentication/filtering, idempotency/supersession, durable lifecycle/deadline, Check mapping, GitHub auth/egress, R2 artifacts, Queue/DLQ, and rollout/cleanup.
- [x] 1.2 Record the A1 sequence, persisted state machine, authentication boundary, Check mapping, artifact layout, and required failure matrix in design.md.

## 2. Test-first Worker contracts

- [x] 2.1 Add failing offline tests for HMAC verification, replay/idempotency identity, event filtering, and message derivation.
- [x] 2.2 Add failing offline tests for legal state transitions, duplicate starts, supersession, deadlines, Check conclusions/summaries, and artifact keys.
- [x] 2.3 Add failing offline tests for Codex/GitHub egress host matching, Basic/Bearer rewriting, and credential-free Sandbox environment construction.

## 3. Worker implementation

- [x] 3.1 Implement `/github/webhook`, serializable messages, filtering, constant-time verification, Queue enqueue, and authenticated metadata-only `/jobs/:key` routing while preserving spike gates.
- [x] 3.2 Implement App JWT signing, scoped installation-token exchange/cache, Check Run create/update helpers, and retryable GitHub error classification.
- [x] 3.3 Implement `RvwReviewJob` persistence, idempotent start/supersede, Sandbox provisioning, exact rvw auto command, 30-second alarms, deadline handling, result parsing, R2 streaming, Check publication, and cleanup.
- [x] 3.4 Implement Queue consumer acknowledgement/retry behavior and structured transition/egress logs without credential values.

## 4. Cloud configuration and operations

- [x] 4.1 Add per-environment Queue producer/consumer/DLQ, R2, review-job DO migration, and non-secret vars to Wrangler; regenerate Worker bindings.
- [x] 4.2 Add matching environment-suffixed Terraform R2, Queue, and DLQ resources while preserving the provider pin.
- [x] 4.3 Update the GitHub App manifest, A1 runbook, registration/secrets/re-run/rollout/cleanup instructions, and Terraform-before-Worker release ordering without changing `RVW_CLOUD_DEPLOY`.

## 5. Verification and handoff

- [x] 5.1 Run Python lint/format/type/test gates, OpenSpec main/change validation, and actionlint as bare commands.
- [x] 5.2 Run npm install/type/test, both Wrangler dry-runs, Terraform format/init/validate, and Docker build/remove as bare commands.
- [x] 5.3 Inspect the complete diff, confirm no secrets/runtime artifacts, mark tasks complete, and commit the implementation without pushing.
