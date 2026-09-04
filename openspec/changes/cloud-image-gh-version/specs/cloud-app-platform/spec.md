## ADDED Requirements

### Requirement: Sandbox image ships a compatible reproducible GitHub CLI

The cloud Sandbox image MUST install an exact GitHub CLI release from the official
upstream release archive at `/usr/local/bin/gh`, MUST verify that archive against a
pinned SHA-256 and the checksum manifest from the same release, and MUST NOT install the
distribution-provided `gh` package. The image build MUST fail unless the installed
version is at least the declared minimum version that supports every pull-request field
used by rvw target resolution, including `headRefOid`.

#### Scenario: Sandbox image definition is inspected offline

- **WHEN** a maintainer inspects the cloud Dockerfile without network credentials
- **THEN** it declares exact GitHub CLI and minimum versions, omits `gh` from the
  distribution package list, and verifies the exact official release archive checksum

#### Scenario: Sandbox image is built

- **WHEN** the cloud Sandbox image build installs its declared GitHub CLI release
- **THEN** `/usr/local/bin/gh` reports that exact release and the build-time minimum
  version assertion succeeds
