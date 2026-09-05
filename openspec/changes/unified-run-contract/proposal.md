## Why

The v0.11.5 surface audit demonstrated that all-INVALID discovery can become `auto` PASS, infrastructure exceptions can masquerade as BLOCK, and App terminal paths lose diagnostics. CLI, Actions, and App need one Python-owned execution contract so policy, repository identity, failure classification, and retained evidence agree.

## What Changes

- Implement `rvw run` as the shared policy-gated command with immutable event anchors, an explicit artifact directory, publication mode, and the existing runtime controls; retain `auto` as a compatibility alias.
- **BREAKING**: Reserve run/auto exits 0 for PASS, 1 for BLOCK, 2 for invalid input/configuration, and 3 for infrastructure failure; all-INVALID reviews fail with `review_failed:<detail>`.
- Bind PR URL queries to their repository in Python and resolve auto policies through explicit path, base-commit policy, deprecated external policy, then package default.
- Persist versioned `process.json`, Python-produced `summary.json`, top-level diagnostics, and a complete file-size manifest, including partial runs.
- Replace App stdout parsing, artifact copying/name lists, and independent result recounting with the contract; persist diagnostics before every Sandbox teardown and retain SDK observations as supplements.
- Update Actions to pass event anchors, retain mounted artifacts, render the Python summary, apply a configurable 90-minute timeout, and preserve canonical exit classification.
- Share Codex configuration and GitHub CLI installation resources between images, and remove the App-only policy copy.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `operation-modes`: Shared run command, compatibility alias, exit reservation, and anchor/repository binding.
- `runtime-contract`: Python-owned process envelope and terminal diagnostics.
- `reporting`: Shared summary facts and complete artifact manifests.
- `pr-gate`: Auto-policy resolution precedence and portable default.
- `cloud-app-platform`: Thin App adapter, canonical Check mapping, and terminal-path persistence.
- `container-ci-packaging`: Shared build resources and Actions contract consumption.

## Impact

Python CLI, pipeline, target resolution, policy, summary, store, report, container entrypoint and new package resources; App Worker orchestration and tests; reusable review workflow; both Dockerfiles and build resources; deterministic parity and regression tests. External registry contents, lane implementation/lint/docs, deployment, and secrets are outside scope. Webhook, token injection, Check Run API, R2 transport, lifecycle management, and Actions checkout remain adapter responsibilities.
