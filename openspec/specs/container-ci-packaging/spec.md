# container-ci-packaging

## Purpose

Define the portable, secret-free image and base-controlled GitHub Actions contract
that lets repositories run rvw as a systemic pull-request check.

## Requirements

### Requirement: The container image is a complete rvw runtime

The project MUST provide a multi-stage Linux image containing Python 3.12, an rvw
installation built from the repository source with packaged common lanes, Node 24,
Codex CLI version 0.152.0, Git, GitHub CLI, Bash, coreutils, ripgrep, and the Linux
process utility required by rvw runtime child-lifetime coupling. The image entry point
MUST invoke `rvw` with all caller arguments and MUST support a caller-mounted repository
as its working directory.

#### Scenario: Image runtime is inspected

- **WHEN** an operator builds the repository image and queries its installed tools
- **THEN** Python reports 3.12, Node reports 24, Codex reports 0.152.0, rvw reports the source package version, and packaged common lanes are discoverable

#### Scenario: Caller passes a review command

- **WHEN** the container is started in a mounted checkout with `review --target <sha> --repo-dir <path>` arguments
- **THEN** the entry point executes the equivalent `rvw review` command in that working-directory context

### Requirement: Reusable review image ships a compatible reproducible GitHub CLI

The reusable review image MUST install an exact GitHub CLI release from the official
upstream release archive at `/usr/local/bin/gh`, MUST verify that archive against a
pinned SHA-256 and the checksum manifest from the same release, and MUST NOT install the
distribution-provided `gh` package. The image build MUST fail unless the installed
version is at least the declared minimum version that supports every pull-request field
used by rvw target resolution, including `headRefOid`.

#### Scenario: Reusable image definition is inspected offline

- **WHEN** a maintainer inspects the root Dockerfile without network credentials
- **THEN** it declares exact GitHub CLI and minimum versions, omits `gh` from the
  distribution package list, and verifies the exact official release archive checksum

#### Scenario: Reusable image is built

- **WHEN** the reusable review image build installs its declared GitHub CLI release
- **THEN** `/usr/local/bin/gh` reports that exact release and the build-time minimum
  version assertion succeeds

### Requirement: Container startup materializes secret-free Codex configuration

The image MUST contain a configuration template at a stable system path that selects a
Codex model provider whose credential `env_key` is `CODEX_API_KEY`. At startup the image
MUST materialize the invoking user's `~/.codex/config.toml`, MUST take the provider base
URL from runtime `CODEX_BASE_URL` or an explicitly supplied build-time default, and MUST
preserve a missing base URL as an unconfigured value rather than inserting a personal
infrastructure URL. The image and produced configuration MUST NOT contain an auth token,
`auth.json`, or a secret value.

#### Scenario: Runtime endpoint is supplied

- **WHEN** a container starts with `CODEX_API_KEY` and `CODEX_BASE_URL` in its environment
- **THEN** the materialized provider reads authentication through the declared env key and contains the supplied base URL without copying the API key into the configuration

#### Scenario: No endpoint is supplied

- **WHEN** neither a runtime base URL nor a build-time default was supplied
- **THEN** the materialized configuration contains no personal endpoint default and startup does not create `auth.json`

### Requirement: Release publication preserves the container build contract

The release workflow MUST build the image from the checked-out tag with
`RVW_IMAGE_VERSION` set to the normalized release version and `CODEX_BASE_URL` set to
the documented empty, non-personal default. It MUST verify that the normalized tag,
package metadata, and runtime version agree before pushing the image, and the build MUST
NOT receive a Codex credential, PyPI credential, or personal endpoint.

#### Scenario: Tagged image is built

- **WHEN** release tag `vX.Y.Z` reaches the image publication job
- **THEN** the image is built from that tagged source with `RVW_IMAGE_VERSION=X.Y.Z` and an empty `CODEX_BASE_URL`

#### Scenario: Release versions diverge

- **WHEN** the normalized tag version does not match package metadata or the runtime version
- **THEN** image publication exits nonzero before the image build or registry push

### Requirement: Reusable review workflow is base-controlled and immutable-targeted

The project MUST provide a reusable workflow callable by a thin target-repository
workflow triggered by `pull_request_target`. The caller MUST select an explicit image
reference. The reusable job MUST check out the event's immutable PR head SHA without
persisting credentials, fetch the recorded base SHA, and execute the image with the
equivalent of `rvw auto --target <pr-number> --repo-dir <checkout>`. The PR target MUST
resolve to the checked-out event head SHA or checkout verification MUST fail closed. It MUST map
`CODEX_API_KEY`, optional `CODEX_BASE_URL`, and a job-scoped `GITHUB_TOKEN` into the
container, and MUST grant only repository-content read and pull-request COMMENT
publication permissions.

#### Scenario: Pull request review runs from the base workflow

- **WHEN** a target repository's protected caller receives a `pull_request_target` event and invokes the reusable workflow with a pinned image tag
- **THEN** the reusable job runs the base-side workflow definition against the event's exact head SHA with the base commit available locally

#### Scenario: Policy requests COMMENT publication

- **WHEN** repository auto policy selects COMMENT publication
- **THEN** rvw can use the mapped GitHub token to publish finding narratives without emitting an approving review

### Requirement: The workflow job is the review check

The reusable workflow MUST propagate the `rvw auto` process status without a
continue-on-error or success override, so PASS exits zero and BLOCK exits one. Project
documentation MUST describe the job as the initial check surface and MUST NOT claim that
the check is required or configure branch protection.

#### Scenario: Auto policy blocks a change

- **WHEN** containerized `rvw auto` returns its BLOCK exit status
- **THEN** the reusable workflow job fails while any COMMENT narrative remains auxiliary evidence

#### Scenario: Auto policy passes a change

- **WHEN** containerized `rvw auto` returns its PASS exit status
- **THEN** the reusable workflow job succeeds

### Requirement: Headless smoke records the container isolation evidence

The implementation verification MUST build the local image and run a real agentic target-repository
review from two detached, read-only mounted clones at a pinned commit. The smoke MUST
record whether env-only Codex authentication succeeds without `auth.json`, whether Codex
read-only sandboxing works within the default container boundary, and whether the full
run completes with valid lanes and covered receipts. If the read-only sandbox is not
available, rvw MAY use `danger-full-access` only inside the container boundary and MUST
record the failure evidence and fallback decision. Environmental failure MUST be
reported with the exact error rather than represented as a successful run.

#### Scenario: Default container sandbox is supported

- **WHEN** the live smoke completes with Codex `--sandbox read-only`
- **THEN** the report records env-only authentication, read-only isolation, lane validity, receipt coverage, and evidence paths

#### Scenario: Container host cannot provide read-only sandboxing

- **WHEN** the live smoke fails specifically because the inner Codex sandbox is unavailable
- **THEN** verification retries with container-bounded `danger-full-access` and records both the original error and the fallback result
