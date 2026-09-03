interface DeployerBindings {
  /** Required deployer var supplied outside the committed Wrangler config. */
  CODEX_PROXY_HOST?: string;
  /** Required deployer var supplied outside the committed Wrangler config. */
  GITHUB_APP_ID?: string;
  /** Secret binding provisioned with `wrangler secret put CODEX_API_KEY`. */
  CODEX_API_KEY: string;
  /** Secret binding provisioned with `wrangler secret put GITHUB_APP_PRIVATE_KEY`. */
  GITHUB_APP_PRIVATE_KEY: string;
  /** Secret binding provisioned with `wrangler secret put GITHUB_WEBHOOK_SECRET`. */
  GITHUB_WEBHOOK_SECRET: string;
  /** Secret binding provisioned with `wrangler secret put RVW_ADMIN_TOKEN`. */
  RVW_ADMIN_TOKEN: string;
}

interface Env extends DeployerBindings {}

declare namespace Cloudflare {
  interface Env extends DeployerBindings {}
}
