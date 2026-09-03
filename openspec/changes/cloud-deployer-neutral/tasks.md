## 1. Regression coverage

- [x] 1.1 Add failing Worker tests for required configuration, structured fail-closed responses, and runtime host-map isolation across two configured hosts plus an unconfigured environment.
- [x] 1.2 Replace PR #53 tests that require a committed GitHub App ID with deployer-neutral configuration and documentation assertions.
- [x] 1.3 Add tests for the tracked-file neutrality guard, including forbidden tokens, account-shaped identifiers, exclusions, and canonical project URL allowances.

## 2. Worker and deployment configuration

- [x] 2.1 Implement centralized required-var validation and structured `config_missing` errors at request, queue, Durable Object start, and alarm entries.
- [x] 2.2 Initialize Sandbox outbound hosts empty and rebuild the host map only from a validated runtime `CODEX_PROXY_HOST`; remove every proxy fallback.
- [x] 2.3 Remove committed `CODEX_PROXY_HOST` and `GITHUB_APP_ID` Wrangler values, regenerate/adjust runtime types to plain strings, and verify both Wrangler environment dry-runs remain offline.
- [x] 2.4 Convert the GitHub App manifest to deployer-filled fork and Worker-host placeholders.

## 3. Infrastructure and documentation

- [x] 3.1 Remove redundant Cloudflare provider token variable plumbing while preserving standard environment/secret credential flow for Terraform and the R2 backend.
- [x] 3.2 Rewrite cloud, infrastructure, bootstrap, and container CI instructions as deployer-neutral guidance and add the exact required vars, secrets, Terraform vars, and state credential table.
- [x] 3.3 Update the main cloud-app-platform specification to match the implemented deployer-neutral and fail-closed behavior.

## 4. Mechanical guard and CI

- [x] 4.1 Implement the standard-library tracked-file deployer-neutrality guard with scoped exclusions and file:line diagnostics.
- [x] 4.2 Wire the guard into CI and confirm the final tracked tree reports clean.

## 5. Verification and delivery

- [x] 5.1 Run all Python, OpenSpec, actionlint, Worker, Wrangler, Terraform, Docker, and neutrality gates as bare commands and resolve failures.
- [ ] 5.2 Inspect the final diff against `feat/cloud-tf-r2-backend`, commit, push `feat/cloud-deployer-neutral`, and open a PR with the requested stacked base.
