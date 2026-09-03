## Why

The A0 scaffold proves that rvw can run in a Cloudflare Sandbox, but a production GitHub App needs authenticated webhook intake, at-least-once Queue delivery, a durable observer for reviews that commonly run longer than 25 minutes, persisted artifacts, and a Check Run that reports review semantics without treating infrastructure failures as code failures.

## What Changes

- Add verified, filtered GitHub webhook intake and idempotent Queue messages for pull-request reviews and Check Run re-requests.
- Add one durable review job per installation/repository/PR/head identity, with alarm-driven Sandbox observation, supersession, and a configurable 90-minute default deadline.
- Add GitHub App JWT and installation-token authentication, Check Run publication, and per-sandbox GitHub egress credential injection.
- Persist review artifacts to R2 and expose authenticated metadata-only job status for operators.
- Bind per-environment Queues, a DLQ, R2, and the review-job Durable Object; declare matching Terraform resources and safe release ordering.
- Document GitHub App registration, secrets, asynchronous container rollout readiness, re-runs, and three-resource cleanup.

## Capabilities

### Modified Capabilities

- `cloud-app-platform`: implement the A1 GitHub App review pipeline and its operational contracts.
- `release-automation`: provision bound Queue and R2 resources before deploying the Worker that consumes them.

## Impact

The change adds TypeScript Worker modules and offline Vitest coverage under `cloud/`, Cloudflare Queue/R2/DO bindings, Terraform Queue/DLQ/R2 resources, GitHub App manifest events, and runbook/release-workflow updates. It does not deploy resources, register an App, create secrets, modify the external review registry, or change Python behavior.
