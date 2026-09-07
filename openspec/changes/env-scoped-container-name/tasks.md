## 1. Regression coverage

- [x] 1.1 Add an offline test that parses `cloud/wrangler.jsonc` and asserts the default, `spike`, and `prod` container application names are distinct and end with their environment name while the `RvwSandbox` class is unchanged.
- [x] 1.2 Add an offline test that executes the deploy workflow's container-name resolver for `spike` and `prod` and proves it refuses to fall back to the top-level entry for an environment that declares no containers.

## 2. Deployment configuration

- [x] 2.1 Rename the container application to `rvw-sandbox-dev`, `rvw-sandbox-spike`, and `rvw-sandbox-prod` without changing class, image, build context, instance type, or instance limits.
- [x] 2.2 Resolve the selected environment's container application name in the `Deploy Worker` step, fail closed on a missing or unscoped entry, export it for later steps, and use it for the previous-digest capture and rollout wait; remove the "same across envs" assumption.

## 3. Specification and documentation

- [x] 3.1 Add the per-environment container application name requirement and the environment-scoped rollout-wait wording to the `cloud-app-platform` main specification.
- [x] 3.2 Record the measured 2026-09-07 failure, the naming decision, the Wrangler default-name alternative, and the migration consequence in `cloud-app-platform` context.
- [x] 3.3 State in `cloud/README.md` that the application is named per environment and that migrating an existing environment creates a new application whose predecessor the deployer deletes.

## 4. Verification

- [x] 4.1 Run the Python, OpenSpec, actionlint, Worker, Wrangler dry-run (`spike` and `prod`), and deployer-neutrality gates as bare commands.
- [x] 4.2 Confirm no `rvw-sandbox` reference without an environment suffix remains outside historical context, then commit without pushing.
