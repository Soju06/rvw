## ADDED Requirements

### Requirement: Opt-in cloud releases coordinate Terraform through R2 state

When the existing `RVW_CLOUD_DEPLOY` gate permits `deploy-cloud`, the release workflow MUST initialize Terraform's S3-compatible backend for key `rvw/prod/terraform.tfstate` in bucket `rvw-terraform-state` before applying infrastructure. It MUST obtain R2 S3 credentials from repository secrets `R2_STATE_ACCESS_KEY_ID` and `R2_STATE_SECRET_ACCESS_KEY`, supply them through the process environment, and MUST NOT reuse the Cloudflare account API token as an S3 credential or expose either credential in workflow arguments or logs.

#### Scenario: Cloud release deployment is enabled
- **WHEN** shared release gates pass and `vars.RVW_CLOUD_DEPLOY` is exactly `true`
- **THEN** `deploy-cloud` initializes locked production state from the owner-provisioned R2 S3 secrets, applies Terraform, and then deploys the production Worker

#### Scenario: Cloud release deployment is disabled
- **WHEN** `vars.RVW_CLOUD_DEPLOY` is not exactly `true`
- **THEN** no R2 state credential is consumed and no Cloudflare provisioning or deployment runs
