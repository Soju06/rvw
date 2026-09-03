output "artifacts_bucket" {
  value = cloudflare_r2_bucket.artifacts.name
}

output "artifacts_bucket_id" {
  value = cloudflare_r2_bucket.artifacts.id
}

output "review_jobs_queue" {
  value = cloudflare_queue.review_jobs.queue_name
}

output "review_jobs_queue_id" {
  value = cloudflare_queue.review_jobs.id
}

output "review_jobs_dlq" {
  value = cloudflare_queue.review_jobs_dlq.queue_name
}

output "review_jobs_dlq_id" {
  value = cloudflare_queue.review_jobs_dlq.id
}

output "worker_name" {
  value = "${var.name_prefix}-cloud-${var.environment}"
}

output "durable_object_classes" {
  value = ["RvwSandbox", "RvwReviewJob"]
}
