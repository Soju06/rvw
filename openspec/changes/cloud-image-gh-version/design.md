## Context

Both image definitions currently install `gh` from an unpinned Debian package list.
rvw passes `_PR_FIELDS`, including `headRefOid`, to `gh pr view`; see the proposal for
the measured failure. Official GitHub CLI v2.18.0 release notes identify that release as
the first to add `headRefOid`, while the latest stable release measured on 2026-09-04 is
v2.100.0.

## Goals / Non-Goals

**Goals:**

- Make the GitHub CLI binary and its compatibility floor explicit in both images.
- Authenticate the selected upstream archive with immutable repository-owned values and
  the upstream manifest.
- Keep the compatibility regression test deterministic and offline.

**Non-Goals:**

- Change rvw's target-resolution fields or add a runtime GitHub API probe.
- Support additional container architectures in this change.
- Deploy, publish, or otherwise mutate a live cloud environment or image registry.

## Decisions

### Pin the official tar archive and checksum in each runtime stage

Each Dockerfile declares `GH_VERSION=v2.100.0` and the published archive SHA-256, fetches
the Linux amd64 archive and `checksums.txt` from that exact tag, verifies that the
manifest entry equals the pinned checksum, and runs `sha256sum --check` before extracting
only `gh` to `/usr/local/bin`. The tar archive avoids installing a distribution package
with dependency or path behavior outside the image definition. Fetching only the archive
without pinning its digest was rejected because a tag alone does not authenticate bytes.

### Declare the upstream compatibility floor separately from the selected pin

`MIN_GH_VERSION=2.18.0` records the first official release with `headRefOid`. The build
checks the installed version both against the exact selected release and against that
minimum. Using the selected v2.100.0 as the minimum was rejected because it would obscure
the actual compatibility contract and unnecessarily couple future pin changes to it.

### Enforce the Dockerfile contract with offline parsing

A focused Python test parses both Dockerfiles and checks their package lists, semantic
version arguments, official exact-tag URLs, checksum verification, install path, and
version gate. A live GitHub command cannot be a deterministic unit test, and help-text
field enumeration is not the durable compatibility assertion.

## Risks / Trade-offs

- **[The amd64 asset excludes other build architectures]** → Both current image paths
  target Linux amd64; multi-architecture selection remains a separate change.
- **[GitHub release availability becomes a build dependency]** → Exact tag, filename,
  and checksum pins make failures explicit and prevent silent substitution.
- **[Version comparison can accidentally accept a different binary]** → Install to
  `/usr/local/bin`, invoke it during the same build step, and require both exact-pin and
  minimum-version checks.

## Migration Plan

Merge the Dockerfile, test, and synchronized specification changes together. Existing
consumers receive the new binary on their next image build or release. Rollback restores
the prior image definitions; no runtime data migration or deployment action is required.
