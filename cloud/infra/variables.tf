variable "account_id" {
  type        = string
  description = "Cloudflare account ID."
}

variable "environment" {
  type        = string
  description = "Deployment environment suffix."
  validation {
    condition     = contains(["dev", "spike", "prod"], var.environment)
    error_message = "environment must be dev, spike, or prod"
  }
}
