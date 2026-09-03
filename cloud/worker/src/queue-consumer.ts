import {idempotencyKey, validateReviewJobMessage, type ReviewJobMessage} from "./webhook";

const FINAL_DELIVERY_ATTEMPT = 4;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function consumeReviewJobs(batch: MessageBatch<unknown>, env: Env): Promise<void> {
  for (const queuedMessage of batch.messages) {
    let body: ReviewJobMessage;
    try {
      body = validateReviewJobMessage(queuedMessage.body);
      if (body.previousHeadSha !== undefined && body.previousHeadSha !== body.headSha) {
        const previousKey = idempotencyKey(
          body.installationId,
          body.repoId,
          body.prNumber,
          body.previousHeadSha,
        );
        await env.RVW_REVIEW_JOB.getByName(previousKey).supersede(
          previousKey,
          `superseded by ${body.jobId}`,
        );
      }
      await env.RVW_REVIEW_JOB.getByName(body.idempotencyKey).start({
        ...body,
        attempt: queuedMessage.attempts,
      });
      queuedMessage.ack();
    } catch (error) {
      const reason = errorMessage(error);
      console.error(
        JSON.stringify({
          event: "review_job_queue_failure",
          messageId: queuedMessage.id,
          attempt: queuedMessage.attempts,
          error: reason,
        }),
      );
      if (queuedMessage.attempts >= FINAL_DELIVERY_ATTEMPT) {
        try {
          const finalBody = validateReviewJobMessage(queuedMessage.body);
          await env.RVW_REVIEW_JOB.getByName(finalBody.idempotencyKey).failStart(
            finalBody,
            `Queue retries exhausted: ${reason}`,
          );
        } catch (finalizeError) {
          console.error(
            JSON.stringify({
              event: "review_job_dlq_finalize_failure",
              messageId: queuedMessage.id,
              error: errorMessage(finalizeError),
            }),
          );
        }
      }
      queuedMessage.retry({delaySeconds: 30});
    }
  }
}
