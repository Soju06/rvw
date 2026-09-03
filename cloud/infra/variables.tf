variable "account_id" {
  type        = string
  description = "Cloudflare account ID."
  nullable    = false
  validation {
    condition     = can(regex("^[0-9a-fA-F]{32}$", var.account_id))
    error_message = "account_id must be a 32-character hexadecimal Cloudflare account ID."
  }
}

variable "environment" {
  type        = string
  description = "Deployment environment suffix."
  nullable    = false
  validation {
    condition     = contains(["spike", "prod"], var.environment)
    error_message = "environment must be spike or prod."
  }
}

variable "name_prefix" {
  type        = string
  description = "Prefix used for resources when an explicit override is not supplied."
  default     = "rvw"
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,39}$", var.name_prefix))
    error_message = "name_prefix must start with a lowercase letter and contain only lowercase letters, digits, or hyphens."
  }
}

variable "queue_name" {
  type        = string
  description = "Optional review queue name override."
  default     = null
  nullable    = true
  validation {
    condition     = var.queue_name == null || can(regex("^[a-z][a-z0-9-]{0,62}$", var.queue_name))
    error_message = "queue_name must be null or a lowercase queue name up to 63 characters."
  }
}

variable "queue_dlq_name" {
  type        = string
  description = "Optional review queue dead-letter queue name override."
  default     = null
  nullable    = true
  validation {
    condition     = var.queue_dlq_name == null || can(regex("^[a-z][a-z0-9-]{0,62}$", var.queue_dlq_name))
    error_message = "queue_dlq_name must be null or a lowercase queue name up to 63 characters."
  }
}

variable "artifacts_bucket_name" {
  type        = string
  description = "Optional R2 artifacts bucket name override."
  default     = null
  nullable    = true
  validation {
    condition     = var.artifacts_bucket_name == null || can(regex("^[a-z][a-z0-9-]{2,62}$", var.artifacts_bucket_name))
    error_message = "artifacts_bucket_name must be null or a lowercase R2 bucket name between 3 and 63 characters."
  }
}

variable "bucket_name" {
  type        = string
  description = "Optional alias for the R2 artifacts bucket name override."
  default     = null
  nullable    = true
  validation {
    condition     = var.bucket_name == null || can(regex("^[a-z][a-z0-9-]{2,62}$", var.bucket_name))
    error_message = "bucket_name must be null or a lowercase R2 bucket name between 3 and 63 characters."
  }
}
