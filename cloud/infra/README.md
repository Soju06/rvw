# Terraform (A1 resources)

All deployer-specific values remain outside this repository. Provide
`account_id` and `environment` as Terraform variables, `CLOUDFLARE_API_TOKEN`
through the provider's standard environment variable, and
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from the R2 state credentials.

This directory declares the R2 artifact bucket, review Queue, and dead-letter
Queue used by A1. Resource names are suffixed with `dev`, `spike`, or `prod` and
match the corresponding Wrangler bindings.

## Offline validation

The backend is partial by design. CI and local checks need no cloud credentials:

```bash
terraform init -backend=false
terraform validate
```

## Remote state initialization

Bootstrap `rvw-terraform-state` and its dedicated R2 S3 credentials once by
following [`bootstrap/README.md`](bootstrap/README.md). The same bucket stores one
state object per environment at `rvw/<environment>/terraform.tfstate`; Terraform
also manages the adjacent `.tflock` object. Do not create a DynamoDB table.

Set `environment` to `dev`, `spike`, or `prod`. Supply credentials through the
standard AWS environment names so Terraform does not copy them from command-line
backend configuration into local metadata:

```bash
export AWS_ACCESS_KEY_ID="$R2_STATE_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_STATE_SECRET_ACCESS_KEY"

terraform init \
  -backend-config="bucket=rvw-terraform-state" \
  -backend-config="key=rvw/${environment}/terraform.tfstate" \
  -backend-config="region=auto" \
  -backend-config="endpoints={s3=\"https://${CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com\"}" \
  -backend-config="use_path_style=true" \
  -backend-config="skip_credentials_validation=true" \
  -backend-config="skip_metadata_api_check=true" \
  -backend-config="skip_region_validation=true" \
  -backend-config="skip_requesting_account_id=true" \
  -backend-config="skip_s3_checksum=true"
```

The Cloudflare provider separately consumes `CLOUDFLARE_API_TOKEN`, plus
`account_id` and `environment` variables. No credential belongs in this directory.
Before the first shared apply, deliberately migrate any existing local state with
`terraform init -migrate-state` and the same backend configuration. Never delete
the bootstrap bucket as part of an environment destroy or code rollback.
