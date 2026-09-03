# One-time Terraform state bootstrap

The state bucket cannot be managed by the state it will contain. An account owner
creates it once with the regular Cloudflare account API token from `cloud/`:

```bash
npx wrangler r2 bucket create rvw-terraform-state
```

Do not add this bucket to `cloud/infra/main.tf`, and do not delete it during normal
environment cleanup.

Next, in **Cloudflare Dashboard → R2 → Manage R2 API tokens**, create a dedicated
token with **Object Read and Write** (`Object Read & Write`) permission. Choose
**Apply to specific buckets only** and select only `rvw-terraform-state`. Record
the one-time Access Key ID and Secret Access Key in the repository secret store as:

- `R2_STATE_ACCESS_KEY_ID`
- `R2_STATE_SECRET_ACCESS_KEY`

R2 S3 credentials are separate from `CLOUDFLARE_API_TOKEN`; the account API token
used by Wrangler and the Terraform Cloudflare provider is not an S3 Access Key ID
or Secret Access Key. Never commit either value or pass it in a Terraform backend
argument. The scoped token needs object read/write/list/delete behavior so
Terraform can maintain both state and native `.tflock` objects.
