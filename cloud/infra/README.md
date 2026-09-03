# Terraform (A1 resources)

This directory declares the R2 artifact bucket, review Queue, and dead-letter
Queue used by A1. Resource names are suffixed with `dev`, `spike`, or `prod` and
match the corresponding Wrangler bindings.
Run `terraform init -backend=false` and `terraform validate` offline. CI supplies
`account_id`, `environment`, and the token through secrets; no token belongs here.
State uses the local backend for now. Move it to a locked R2 backend before shared
production operation.
