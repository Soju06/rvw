# Minimal rvw deployer

This directory is a complete consumer-side layout. Copy it into a private
deployment repository, replace every angle-bracket placeholder, and provide
Cloudflare/R2 credentials through the consumer's secret store. The rvw project
publishes these assets; the consumer owns Terraform state and deployment.

Initialize Terraform with the R2 backend example and a private tfvars file:

```bash
terraform init -backend-config=backend.hcl
terraform apply
```

The example workflow calls rvw's reusable deploy workflow. For every upgrade,
bump the module `source` `ref` and the workflow `uses` `@tag` together to the
same release tag. Do not copy or merge `wrangler.jsonc`; the reusable workflow
checks out that tag and supplies deployer values with Wrangler CLI overrides.

All values in this example are placeholders. Keep real account IDs, hosts,
tokens, keys, and webhook secrets in the consumer repository's private
variables/secrets only.
