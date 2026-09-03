## Context

See `proposal.md` for motivation. The Worker currently mutates the Sandbox class's static `outboundByHost` map at entry points, but initializes it with a deployer hostname and silently restores that hostname for missing configuration. GitHub App identity is likewise committed in Wrangler. Runtime bindings are available only when a request, queue delivery, or Durable Object invocation supplies `env`; Wrangler dry-run must remain independent of runtime values.

## Goals / Non-Goals

**Goals:**

- Validate all required non-secret deployment identity once at each external execution entry before side effects.
- Register the Codex outbound handler from the validated host at runtime and make missing configuration incapable of registering any host.
- Keep deployment values in deployer-owned workflow inputs, Wrangler overrides, or secrets without weakening offline validation.
- Detect regressions across tracked shipping and instructional files with a deterministic standard-library guard.

**Non-Goals:**

- Changing project-generic Worker, container, Queue, bucket, or state-bucket names.
- Deploying resources, registering a GitHub App, or creating secrets.
- Scanning tests or historical OpenSpec context, whose fixtures and decision record may intentionally contain forbidden tokens.

## Decisions

### Centralize required configuration validation

A small Worker configuration module will trim and validate `CODEX_PROXY_HOST` and `GITHUB_APP_ID`, returning a typed snapshot. Missing values raise a dedicated error whose message and serializable fields are `config_missing` plus the variable name. Fetch converts it to a structured JSON service error; queue and Durable Object entry points preserve the typed/message form for retry and structured logs. This is preferable to scattered truthiness checks because a validated snapshot prevents later fallback and ensures whitespace-only values fail.

### Register the validated host through the SDK's per-Sandbox API

The Sandbox SDK explicitly keeps the Sandbox Durable Object and
`ContainerProxy` handler registries in separate execution contexts. A static
host map assigned from a request entry point therefore cannot reliably reach
the proxy context. Instead, the Codex injector is declared as a module-load
named outbound handler, and each Sandbox receives the validated host through
`setOutboundByHost(host, "codex")` before a process starts or resumes. The SDK
persists this hostname-to-handler override and carries it to `ContainerProxy`,
where the named handler receives the Worker environment and secret binding.

This is the same supported runtime registration pattern already used for the
GitHub API and clone handlers. Tests exercise two Sandbox instances with
distinct configured hosts and an absent configuration, proving each instance
registers only its selected host and missing configuration makes no registration.

### Treat Wrangler vars as deployment overlays

The committed default, `spike`, and `prod` environments omit `CODEX_PROXY_HOST` and `GITHUB_APP_ID`. Wrangler dry-run validates bindings without executing the Worker, while deployers provide these values through private configuration/CI overrides. Generated types declare both as plain strings rather than value literals so implementation remains strict without suggesting a default.

### Scan Git-tracked files, not filesystem leftovers

The Python guard obtains candidates from `git ls-files` and limits them to `cloud/`, `src/`, `.github/`, `Dockerfile`, `docker/`, and `docs/`. It excludes tests and OpenSpec context by construction, scans case-insensitively for the named tokens, and separately flags a 32-hex identifier on an account-bearing line. Findings are stable `file:line` diagnostics. Using Git's tracked set avoids build outputs and ignored local files; a non-Git invocation fails clearly rather than silently scanning a different scope.

### Keep provider credentials in standard environment variables

Terraform's Cloudflare provider reads `CLOUDFLARE_API_TOKEN` directly. The provider token variable and `TF_VAR_cloudflare_api_token` bridge are removed, while `TF_VAR_account_id` remains the non-secret Terraform input and R2 backend credentials continue through `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

## Risks / Trade-offs

- [Existing deployments relied on committed defaults] → Document every required value and require deployers to add private Wrangler/workflow overrides before serving traffic.
- [A Sandbox could start before its egress override is persisted] → Await runtime host registration before every process start or alarm-side process observation.
- [The lexical guard can report an identifier in benign prose] → Keep its scope narrow, exclude tests/history, and allow only documented canonical project URLs.
- [Generated Wrangler types may be overwritten] → Regenerate after configuration changes, then retain explicit runtime-only string declarations if Wrangler omits vars that are intentionally supplied as deployment overrides.

## Migration Plan

1. Add `CODEX_PROXY_HOST` and `GITHUB_APP_ID` to each deployer's private deployment configuration or CI variables.
2. Provision the four Worker secrets and Terraform/backend credentials documented in the runbook.
3. Consume the reusable workflow and committed Wrangler environments with private overrides, then run dry-run/offline gates.
4. Deploy only after configuration is present. Rollback requires restoring the prior code while retaining deployer-owned values; no state migration is involved.
