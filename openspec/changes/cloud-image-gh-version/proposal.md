## Why

The 2026-09-04 cloud E2E run failed before review dispatch because the Sandbox image's
GitHub CLI rejected rvw's required `headRefOid` pull-request field. Both distributed
images need an explicit, verifiable GitHub CLI compatibility contract instead of
inheriting whichever `gh` build their Debian base currently supplies.

## What Changes

- Install an exact GitHub CLI release in both images from official upstream assets.
- Verify the downloaded archive against both a pinned SHA-256 and the same release's
  published checksum manifest before installing it at `/usr/local/bin/gh`.
- Fail image builds unless the installed GitHub CLI meets rvw's minimum version for
  pull-request target-resolution fields.
- Add deterministic repository-contract tests and record the measured cloud failure.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: Require the Sandbox image to ship a pinned, checksum-verified
  GitHub CLI compatible with rvw target resolution.
- `container-ci-packaging`: Apply the same GitHub CLI supply-chain and compatibility
  contract to the reusable review image.

## Impact

This changes `cloud/Dockerfile`, the root `Dockerfile`, offline container contract tests,
and the two related OpenSpec capabilities. It downloads public GitHub release assets at
image-build time but does not deploy an image, modify the external registry, or handle
credentials.
