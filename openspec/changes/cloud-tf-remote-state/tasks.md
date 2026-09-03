## 1. Regression contracts

- [x] 1.1 Add failing deterministic tests for the Terraform S3 backend, Terraform version floor, native lockfile, partial secret-free configuration, and one-time bootstrap documentation.
- [x] 1.2 Add failing deterministic tests for App ID consistency, the `rvw-review` installation URL, and release workflow R2 state initialization/secret mapping.

## 2. Infrastructure and configuration

- [x] 2.1 Replace the local Terraform backend with the partial R2-compatible S3 backend and retain offline initialization/validation.
- [x] 2.2 Add the state-bucket bootstrap runbook with bucket-scoped R2 S3 token guidance and environment-keyed initialization examples.
- [x] 2.3 Set App ID `4813211` in every Wrangler environment, regenerate bindings if needed, and update the cloud runbook with the registered App identity and installation URL.
- [x] 2.4 Update the opt-in release workflow to initialize locked production R2 state from dedicated repository secrets before Terraform apply and Worker deployment.

## 3. Verification and delivery

- [x] 3.1 Run all Python, OpenSpec, actionlint, TypeScript/Vitest, Wrangler dry-run, Terraform offline validation, and Docker build gates as bare commands.
- [x] 3.2 Inspect the complete diff for secrets and scope, mark tasks complete, commit, push `feat/cloud-tf-r2-backend`, and open a pull request to `main`.
