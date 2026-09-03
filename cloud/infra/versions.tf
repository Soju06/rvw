terraform {
  required_version = ">= 1.10.0"
  required_providers {
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 5.0" }
  }
  # Bucket, key, R2 endpoint, and credentials are partial configuration supplied
  # by the operator at init time. Credentials come from AWS_* environment vars.
  backend "s3" {
    use_lockfile = true
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
