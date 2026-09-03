terraform {
  required_version = ">= 1.10.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }

  backend "s3" {}
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

variable "cloudflare_api_token" {
  type        = string
  description = "Cloudflare API token supplied through a private variable or environment."
  sensitive   = true
}

variable "account_id" {
  type        = string
  description = "Cloudflare account ID."
}

variable "environment" {
  type        = string
  description = "rvw environment to provision."
  validation {
    condition     = contains(["spike", "prod"], var.environment)
    error_message = "environment must be spike or prod."
  }
}

module "rvw" {
  # Replace Soju06 with the owner of the rvw repository you consume.
  source      = "github.com/Soju06/rvw//cloud/infra?ref=v0.10.0"
  account_id  = var.account_id
  environment = var.environment
}

output "review_jobs_queue" {
  value = module.rvw.review_jobs_queue
}

output "review_jobs_dlq" {
  value = module.rvw.review_jobs_dlq
}

output "artifacts_bucket" {
  value = module.rvw.artifacts_bucket
}
