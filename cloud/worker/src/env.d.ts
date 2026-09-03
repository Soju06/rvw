interface Env {
  /** Secret binding provisioned with `wrangler secret put CODEX_API_KEY`. */
  CODEX_API_KEY: string;
  /** Secret binding provisioned with `wrangler secret put GITHUB_APP_PRIVATE_KEY`. */
  GITHUB_APP_PRIVATE_KEY: string;
  /** Secret binding provisioned with `wrangler secret put GITHUB_WEBHOOK_SECRET`. */
  GITHUB_WEBHOOK_SECRET: string;
  /** Secret binding provisioned with `wrangler secret put RVW_ADMIN_TOKEN`. */
  RVW_ADMIN_TOKEN: string;
}
