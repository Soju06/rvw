## RENAMED Requirements

- FROM: `### Requirement: Reusable review image ships a compatible reproducible GitHub CLI`
- TO: `### Requirement: Root review image ships a compatible reproducible GitHub CLI`

## MODIFIED Requirements

### Requirement: Root review image ships a compatible reproducible GitHub CLI

The root review image MUST install an exact GitHub CLI release from the official
upstream release archive at `/usr/local/bin/gh`, MUST verify that archive against a
pinned SHA-256 and the checksum manifest from the same release, and MUST NOT install the
distribution-provided `gh` package. The image build MUST fail unless the installed
version is at least the declared minimum version that supports every pull-request field
used by rvw target resolution, including `headRefOid`.

#### Scenario: Root image definition is inspected offline

- **WHEN** a maintainer inspects the root Dockerfile without network credentials
- **THEN** it declares exact GitHub CLI and minimum versions, omits `gh` from the
  distribution package list, and verifies the exact official release archive checksum

#### Scenario: Root image is built

- **WHEN** the root review image build installs its declared GitHub CLI release
- **THEN** `/usr/local/bin/gh` reports that exact release and the build-time minimum
  version assertion succeeds

## REMOVED Requirements

### Requirement: Reusable review workflow is base-controlled and immutable-targeted

**Reason**: The GitHub Actions review surface is retired. The reusable workflow had no consumers, required every consumer repository to hold its own copy of the Codex credential, and could not use the App's egress-proxy credential injection. rvw keeps two review surfaces: the CLI on a host or in the container image, and the GitHub App.

**Migration**: Repositories that want automated review install the rvw GitHub App. Ad-hoc runs invoke the CLI or the published container image directly with `rvw run`.

### Requirement: The workflow job is the review check

**Reason**: No project-owned Actions job exists. The App Check Run and the CLI process exit are the remaining check surfaces, and both already consume the canonical `process.json` and `summary.json` contracts.

**Migration**: Consume the reserved 0/1/2/3 exit of `rvw run` and the `process.json` and `summary.json` artifacts from the App Check Run or from a direct container or CLI invocation.
