# release-automation

## Purpose

Define synchronized release preparation, verified automated and emergency release entry points, trusted PyPI publication, and repository release policy.

## Requirements

### Requirement: Release preparation synchronizes every version surface

The project MUST use release-please with the Python release type to derive releases from Conventional Commits, update `CHANGELOG.md`, and synchronize the versions in `pyproject.toml`, `src/rvw/_version.py`, and the root `rvw` package entry in `uv.lock`.

#### Scenario: Release PR is prepared

- **WHEN** releasable Conventional Commits accumulate on `main`
- **THEN** release-please opens or updates a release PR in which every checked-in rvw version surface has the same proposed version

### Requirement: Automated releases use a personal access token

The release-please workflow MUST authenticate with the `RELEASE_PLEASE_TOKEN` personal access token so that the tags it pushes trigger the tag-event release workflow, and it MUST NOT fall back to the repository `github.token` or publish through a reusable-workflow call.

#### Scenario: Release PR is merged

- **WHEN** a release PR is merged and release-please pushes the version tag with the personal access token
- **THEN** the pushed tag itself triggers the release workflow without any workflow-call chain

#### Scenario: PyPI trusted publishing rejects reusable callers

- **WHEN** the publish job requests its OIDC identity token
- **THEN** the token claims identify the tag-triggered release workflow itself, which PyPI trusted publishing accepts, rather than a reusable workflow invocation, which PyPI rejects

### Requirement: Automated and emergency releases share one verified chain

The release workflow MUST be triggered by pushed `v*` tags as its only entry point,
whether release-please or a maintainer pushes the tag, and every release MUST run the
same gates, tag-to-package version checks, build, PyPI publish, GitHub release-asset,
and GHCR image-publication behavior. PyPI and GHCR publication MUST proceed independently
after their shared gates so failure of either publication path does not prevent the
other path from running.

#### Scenario: Release-please creates a release

- **WHEN** release-please pushes a release tag after the release PR merges
- **THEN** the tag-triggered release workflow runs the full chain, grants the PyPI publication job `id-token: write`, and grants only the GHCR publication job `packages: write`

#### Scenario: Maintainer pushes an emergency tag

- **WHEN** a maintainer pushes a correctly synchronized `vX.Y.Z` tag
- **THEN** the tag-triggered workflow executes the same PyPI and GHCR release behavior using `vX.Y.Z` as its release tag

### Requirement: Release builds fail closed on version mismatch

The release workflow MUST verify that its normalized tag version matches both Python package metadata and the rvw runtime version before building or publishing artifacts.

#### Scenario: Checked-in versions diverge

- **WHEN** the release tag, `pyproject.toml` version, and runtime `__version__` are not identical after removing the tag's `v` prefix
- **THEN** the release workflow exits nonzero before building or publishing

### Requirement: PyPI publication uses trusted publishing

The release workflow MUST publish the built distribution from the protected `pypi` environment with GitHub OIDC and MUST NOT require a PyPI API token.

#### Scenario: Verified build is published

- **WHEN** release gates and version verification pass and the distribution builds successfully
- **THEN** the publish job requests an OIDC identity token and uploads the artifact through PyPI trusted publishing

### Requirement: Changelog and commit policy support deterministic releases

The contribution policy MUST require Conventional Commits with `fix` producing patch intent, `feat` producing minor intent, and `feat!` or a `BREAKING CHANGE` footer producing major intent, and MUST reserve direct `CHANGELOG.md` edits for release-please.

#### Scenario: Contributor prepares a behavioral pull request

- **WHEN** a contributor proposes behavioral work
- **THEN** the contribution guidance requires an OpenSpec change, a Conventional Commit, green CI, a clean `rvw gate --target <pr>` review, and a mergeable clean state

### Requirement: Repository maintenance automation stays scoped to rvw

The repository MUST configure weekly uv and GitHub Actions dependency updates, conservative stale handling with `pinned` and `security` exemptions, and path-based labels for code, tests, OpenSpec, and GitHub configuration without adding unrelated Docker, Bun, beta-channel, Windows-startup, all-contributors, or Codex-review automation.

#### Scenario: Weekly maintenance runs

- **WHEN** scheduled repository maintenance executes
- **THEN** it considers only rvw's Python and GitHub Actions dependencies and preserves protected issues and pull requests from stale closure

### Requirement: Container consumers pin a versioned image reference

The reusable review workflow MUST require its caller to provide an image reference and
MUST NOT supply a floating default image. Target-repository guidance MUST show a
release-version tag pin for explicit upgrades and an immutable digest pin derived from
release output.

#### Scenario: Target repository adopts the workflow

- **WHEN** a target repository creates its thin `pull_request_target` caller
- **THEN** the caller supplies an explicit release-version image tag or its published digest rather than inheriting a mutable image default from rvw

### Requirement: Release tags publish traceable GHCR images

After release gates pass, the tag-triggered workflow MUST build the checked-out release
tag without persisting checkout credentials or using Codex or PyPI credentials,
authenticate to GHCR with the job-scoped `GITHUB_TOKEN`, and publish the same image as
both `ghcr.io/soju06/rvw:v<version>` and `ghcr.io/soju06/rvw:latest`. The GHCR job MUST
receive job-scoped `contents: read` and `packages: write` permissions, and no other
release job MUST receive `packages: write`. The job MUST expose the registry-reported
digest as a job output and record a digest-pinnable image reference in its run summary
or release notes.

#### Scenario: Release image publication succeeds

- **WHEN** shared release gates and image version verification pass for tag `vX.Y.Z`
- **THEN** GHCR receives tags `vX.Y.Z` and `latest` for the same image digest and the workflow exposes `ghcr.io/soju06/rvw@sha256:<digest>` to consumers

#### Scenario: Image publication fails independently

- **WHEN** the GHCR build or push fails after shared gates
- **THEN** its job fails without cancelling, skipping, or blocking the independent PyPI build and publication path

### Requirement: Releases publish reusable deployment artifacts
The tag release rail MUST publish deployment assets without deploying any Cloudflare account or Worker instance. GitHub release notes for each tag MUST include a reusable workflow reference of the form `uses: <owner>/rvw/.github/workflows/rvw-deploy.yml@<tag>` and a Terraform module source of the form `source = "github.com/<owner>/rvw//cloud/infra?ref=<tag>"`, with `<owner>/rvw` derived from `github.repository` and `<tag>` from the release ref.

#### Scenario: Release notes carry upgrade references
- **WHEN** a `vX.Y.Z` tag completes the release rail
- **THEN** the GitHub release notes contain both copyable references for `vX.Y.Z` and no project-owned deployment step ran

### Requirement: Project release workflow has no cloud deployment gate
`release.yml` MUST NOT define a project-owned Cloudflare deployment job or gate. Cloud deployment credentials MUST NOT be required by the release rail.

#### Scenario: Tag release remains publish-only
- **WHEN** a maintainer pushes a release tag
- **THEN** PyPI, GHCR, and GitHub release assets remain eligible after shared gates, while no Cloudflare API operation is scheduled
