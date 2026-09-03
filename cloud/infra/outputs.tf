output "artifacts_bucket" {
  value = cloudflare_r2_bucket.artifacts.name
}

output "review_jobs_queue" {
  value = cloudflare_queue.review_jobs.queue_name
}

output "review_jobs_dlq" {
  value = cloudflare_queue.review_jobs_dlq.queue_name
}
