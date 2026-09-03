## ADDED Requirements

### Requirement: Terraform state is remote, isolated, and lock-protected

Cloud infrastructure MUST declare a partial S3-compatible backend that stores state in the bootstrapped R2 bucket `rvw-terraform-state`, uses key `rvw/<environment>/terraform.tfstate`, and enables Terraform's native S3 lockfile without DynamoDB. The endpoint and R2 S3 credentials MUST be supplied at initialization time and MUST NOT be committed. Terraform MUST require version 1.10 or newer, and credential-free `terraform init -backend=false` followed by `terraform validate` MUST remain supported.

#### Scenario: Shared environment is initialized
- **WHEN** an operator initializes an environment with its R2 endpoint and bucket-scoped S3 credentials
- **THEN** Terraform stores state and its native lockfile under that environment's key in `rvw-terraform-state`

#### Scenario: Offline infrastructure validation runs
- **WHEN** CI initializes Terraform with backend initialization disabled and validates the configuration without cloud credentials
- **THEN** initialization and validation complete without accessing R2

### Requirement: Terraform state storage has an explicit bootstrap boundary

The cloud runbook MUST document that `rvw-terraform-state` is created once before the backend can be initialized, and that its S3 credentials are separate from the Cloudflare account API token. It MUST instruct an owner to create an Object Read and Write R2 API token scoped only to the state bucket and store its Access Key ID and Secret Access Key outside source control.

#### Scenario: Owner bootstraps remote state
- **WHEN** the state bucket and release secrets do not yet exist
- **THEN** the runbook provides a credential-safe one-time bucket creation and bucket-scoped R2 S3 token procedure without minting or recording credentials in the repository

### Requirement: Registered GitHub App identity is consistent

Every Wrangler environment MUST declare non-secret `GITHUB_APP_ID` value `4813211`, and the operator runbook MUST identify the App slug as `rvw-review` and provide its installation URL.

#### Scenario: Any Worker environment is deployed
- **WHEN** Wrangler resolves the default, `spike`, or `prod` environment
- **THEN** the Worker receives App ID `4813211` while App credentials remain secret bindings
