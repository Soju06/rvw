## Why

The reusable GitHub Actions review workflow (`.github/workflows/rvw-review.yml`) was one of three review surfaces alongside the CLI and the GitHub App. A 2026-09-07 audit found zero consumers: GitHub code search returned no callers, and neither clawroid/bori nor APIFuseHQ/apifuse referenced an rvw workflow. The workflow also required every consumer repository to hold its own copy of the Codex credential and could not use the App's egress-proxy credential injection. The owner decided that automated review belongs to the App webhook path, so rvw keeps exactly two review surfaces: the CLI (host or container image) and the GitHub App.

## What Changes

- **BREAKING**: Remove `.github/workflows/rvw-review.yml`. Repositories that want automated review install the rvw GitHub App; ad-hoc runs use the CLI or the published container image directly.
- Retire the `container-ci-packaging` requirements that defined the reusable workflow and its job-as-check contract. Keep the container image, Codex configuration, release publication, shared build resources, smoke evidence, and three-adapter parity requirements, which the CLI and the App Sandbox still use.
- Rewrite the operation-modes, pr-gate, reporting, and release-automation requirements that named Actions as a review surface so they describe the container image and the App.
- Replace the containerized Actions guide with a container image guide covering direct `docker run` usage, release publication, and immutable pins; point the README at the App and the image guide.
- Delete the tests that exercised only the workflow file and its step scripts; add a guard that the review workflow stays removed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-ci-packaging`: Remove the reusable review workflow and job-as-check requirements; rename the image GitHub CLI requirement so it no longer describes a "reusable" image.
- `operation-modes`: Automated invocations are the container image and the App; the App supplies both captured event anchors.
- `pr-gate`: The packaged default policy is available equally to the host CLI, the container image, and the App.
- `reporting`: App Check summaries and other presentations consume the shared summary facts without recounting.
- `release-automation`: Image pin guidance targets direct container runs instead of a workflow caller.

## Impact

`.github/workflows/rvw-review.yml` and its CODEOWNERS entry are removed; `docs/container-ci.md` becomes `docs/container-image.md`; `README.md` links change; `tests/test_container_packaging.py` loses its workflow tests. No Python source changes: `rvw.container_entrypoint`, `rvw run`, and the process/summary contracts are shared by the CLI, the root image, and the App Sandbox command. `.github/workflows/rvw-deploy.yml`, the Worker, Wrangler configuration, Terraform, lanes, and the external registry are unchanged.
