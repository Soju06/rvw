locals {
  queue_name       = coalesce(var.queue_name, "${var.name_prefix}-review-jobs-${var.environment}")
  queue_dlq_name   = coalesce(var.queue_dlq_name, "${var.name_prefix}-review-jobs-dlq-${var.environment}")
  artifacts_bucket = coalesce(var.artifacts_bucket_name, var.bucket_name, "${var.name_prefix}-artifacts-${var.environment}")
}

resource "cloudflare_r2_bucket" "artifacts" {
  account_id = var.account_id
  name       = local.artifacts_bucket
  location   = "enam"
}

resource "cloudflare_queue" "review_jobs" {
  account_id = var.account_id
  queue_name = local.queue_name
}

resource "cloudflare_queue" "review_jobs_dlq" {
  account_id = var.account_id
  queue_name = local.queue_dlq_name
}
