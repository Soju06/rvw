# rvw Terraform module

This directory is the versioned, reusable Terraform module published by rvw.
It declares the Queue, dead-letter Queue, and R2 artifacts bucket used by the
Worker. It deliberately contains no provider credentials and no backend;
consumers own those in their deployment repository.

Inputs are a Cloudflare `account_id`, `environment` (`spike` or `prod`), an
optional `name_prefix` (default `rvw`), and optional queue/DLQ/bucket name
overrides. Outputs expose resource names and IDs plus the derived Worker name
and Durable Object class identifiers for deployer-owned Wrangler configuration.

## Offline validation

```bash
terraform fmt -check
terraform init -backend=false
terraform validate
```

For a complete provider, R2 backend, and reusable-workflow caller layout, see
[`../examples/deployer`](../examples/deployer). Upgrade by pinning this module
source to an rvw release tag and keeping it in lockstep with the workflow tag.
