## MODIFIED Requirements

### Requirement: Automated and emergency releases share one verified chain

The release workflow MUST be triggered by pushed `v*` tags as its only entry point, whether release-please or a maintainer pushes the tag, and every release MUST run the same gates, tag-to-package version checks, build, PyPI publish, GitHub release-asset, and GHCR image-publication behavior. PyPI and GHCR publication MUST proceed independently after their shared gates so failure of either publication path does not prevent the other path from running. A cloud deployment job MAY run in parallel with publication jobs only when repository variable `RVW_CLOUD_DEPLOY` is exactly `true`; it MUST apply Terraform-managed Queue, DLQ, and R2 resources before deploying the production Worker that binds to them.

#### Scenario: Release-please creates a release
- **WHEN** a release PR is merged and release-please pushes the version tag with the personal access token
- **THEN** the tag-triggered workflow runs the full chain, grants the PyPI publication job `id-token: write`, grants only the GHCR publication job `packages: write`, and skips cloud deployment unless `vars.RVW_CLOUD_DEPLOY` is `true`

#### Scenario: Maintainer pushes an emergency tag
- **WHEN** a maintainer pushes a correctly synchronized `vX.Y.Z` tag
- **THEN** the tag-triggered workflow executes the same PyPI, GHCR, and opt-in cloud behavior using `vX.Y.Z` as its release tag

#### Scenario: Cloud deployment ordering
- **WHEN** `vars.RVW_CLOUD_DEPLOY` is `true` and shared gates pass
- **THEN** `deploy-cloud` successfully runs `terraform apply -auto-approve -var environment=prod` before `wrangler deploy --env prod`
