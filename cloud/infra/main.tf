resource "cloudflare_r2_bucket" "artifacts" {
  account_id = var.account_id
  name       = "rvw-artifacts-${var.environment}"
  location   = "enam"
}

resource "cloudflare_queue" "review_jobs" {
  account_id = var.account_id
  queue_name = "rvw-review-jobs-${var.environment}"
}

resource "cloudflare_queue" "review_jobs_dlq" {
  account_id = var.account_id
  queue_name = "rvw-review-jobs-dlq-${var.environment}"
}
