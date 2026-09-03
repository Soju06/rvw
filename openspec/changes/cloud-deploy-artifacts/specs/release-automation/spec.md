## ADDED Requirements

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
