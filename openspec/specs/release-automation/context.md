# Release automation context

## Purpose and scope

This capability governs repository release preparation and publication rather than rvw's runtime review pipeline. Normative behavior is in [spec.md](spec.md).

## Key decisions

- Container consumers explicitly pin both the reusable workflow version and either the
  release image version or its immutable digest. Each pushed release tag publishes the
  matching image plus mutable `latest`; reproducible callers do not consume `latest`.
- The 2026-07-28 v0.2.0 incident demonstrated that manually updating `src/rvw/_version.py` while leaving `pyproject.toml` stale can rebuild an already-published distribution. release-please now writes every version surface, with `tests/test_version_sync.py` retaining a regression guard.
- The release-please manifest starts at the already-published `0.2.0`, so automation proposes only later versions.
- GitHub does not start a new workflow from a tag or release created with the repository
  `GITHUB_TOKEN`. The required `RELEASE_PLEASE_TOKEN` PAT therefore creates release tags
  whose push events start `release.yml` directly; there is no reusable-workflow path.
- `release.yml` has one tag-push entry point for automated and emergency operation. It
  resolves one explicit release tag, checks out that tag, runs the same gates, and
  compares the tag against package and runtime versions before each artifact build.
- PyPI publication remains in the `pypi` GitHub environment and uses OIDC trusted publishing. `skip-existing` makes an identical PAT-triggered duplicate run harmless, but version mismatches still fail before build.
- release-please creates the GitHub Release before the tag-triggered publication workflow
  runs. The final job uploads artifacts to that release, while an emergency tag path
  creates the release when it does not exist.
- GHCR publication is a sibling of the Python build after shared gates. Only that job
  receives `packages: write`, logs in with `GITHUB_TOKEN`, pushes version and `latest`
  tags in one build, and records the registry digest as a job output and step summary.
- The per-tag concurrency group prevents overlapping runs of the same release tag but
  does not serialize different tags updating `latest`; version and digest pins remain
  the stable consumer references.
- The release rail is publish-only for Cloudflare: it adds copyable references to the
  reusable workflow and Terraform module in release notes, while deployers call those
  assets from their own repositories.

## Operational constraints

- `RELEASE_PLEASE_TOKEN` is required so release-please-authored tag pushes trigger the
  release workflow and release-branch updates retrigger checks.
- `CHANGELOG.md` is generated and maintained by release-please and must not be manually edited.
- Required repository labels are administrative GitHub state and are not created by these files.
- The PyPI trusted publisher must continue to authorize the `pypi` environment and `.github/workflows/release.yml`.
- After the first push, an owner must make the GHCR package public for anonymous target
  repository pulls. A pre-existing unlinked package or restrictive organization policy
  may also require granting this repository Actions package-write access; no new secret
  or ordinary repository setting is required for a newly linked package.

## Excluded infrastructure

rvw does not carry image signing, multi-platform manifests, Bun, beta-channel,
Windows-startup, all-contributors, or Codex-review-label automation.

## Historical note

Before this change, a `v*` push independently ran gates, built the package, published to PyPI, and then created a GitHub Release. Version updates and changelog preparation were manual, and the version check inspected only `src/rvw/_version.py`. The synchronized release PR and dual package/runtime validation replace that split contract.
