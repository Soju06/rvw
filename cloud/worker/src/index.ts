import {ConfigMissingError, configErrorResponse, requiredConfig} from "./config";
import {ContainerProxy} from "./sandbox";
import {handleRoute} from "./routes";
import {handleWebhook} from "./webhook";
import {handleJobStatus} from "./job-status";
import {consumeReviewJobs} from "./queue-consumer";

export {ContainerProxy};
export {RvwSandbox} from "./sandbox";
export {RvwReviewJob} from "./review-job";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      const config = requiredConfig(env);
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/healthz") return Response.json({version: env.RVW_VERSION, env: env.RVW_ENV});
      if (request.method === "POST" && url.pathname === "/github/webhook") return await handleWebhook(request, env);
      if (request.method === "GET" && url.pathname.startsWith("/jobs/")) return await handleJobStatus(request, env);
      return await handleRoute(request, env, config);
    } catch (error) {
      if (error instanceof ConfigMissingError) return configErrorResponse(error);
      throw error;
    }
  },
  async queue(batch: MessageBatch<unknown>, env: Env): Promise<void> {
    requiredConfig(env);
    await consumeReviewJobs(batch, env);
  },
} satisfies ExportedHandler<Env>;
