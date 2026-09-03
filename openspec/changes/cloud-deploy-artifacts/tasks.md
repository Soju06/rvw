## 1. OpenSpec contracts

- [x] 1.1 Add cloud-app-platform and release-automation deltas for published
  deployment artifacts, module/workflow contracts, and removal of project-owned
  deployment.
- [x] 1.2 Update main specs and cloud README to state “rvw publishes; you deploy”
  and remove the project-owned deployment behavior.

## 2. Terraform module and example

- [x] 2.1 Refactor `cloud/infra` into a clean versionable module with validated
  variables, overrideable names, provider requirements only, and complete
  outputs.
- [x] 2.2 Add the complete placeholder `cloud/examples/deployer` layout,
  including provider/backend ownership and pinned module source.
- [x] 2.3 Add module and example Terraform format/init-without-backend/validate
  coverage to CI.

## 3. Reusable deployment workflow

- [x] 3.1 Add SHA-pinned `workflow_call` deploy workflow with typed inputs,
  secrets, optional Terraform management, Wrangler deployment, and secret puts.
- [x] 3.2 Implement bounded container digest rollout polling and environment
  health check; verify Wrangler 4.x `--var` syntax and actionlint.
- [x] 3.3 Remove deployer literals from `wrangler.jsonc` and prove CLI vars win in
  spike/prod dry-runs.

## 4. Release rail and verification

- [x] 4.1 Remove the project-owned cloud deployment job/gate and add dynamic
  reusable workflow/module references to GitHub release notes.
- [x] 4.2 Run all requested Python, OpenSpec, workflow, neutrality, npm,
  Wrangler, Terraform, and Docker gates.
- [x] 4.3 Commit, push `feat/cloud-deploy-artifacts`, and open a PR to `main`.
