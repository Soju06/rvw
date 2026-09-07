## Context

See `proposal.md` for motivation. Wrangler deploys `containers[]` entries as
Cloudflare container applications. An application is identified account-wide by
its name and is associated with one Durable Object namespace; deploying a second
Worker whose configuration reuses the name is rejected. The Worker name is
already environment-scoped (`rvw-cloud-<environment>`) and every other bound
resource carries an environment suffix, but the container application name did
not. The `spike` environment is live and receives the GitHub App webhook, so it
must keep working through the rename.

## Goals / Non-Goals

**Goals:**

- Let `spike` and `prod` be deployed into the same Cloudflare account.
- Make the deploy workflow read the selected environment's container name and
  fail closed rather than silently using another environment's entry.
- Prove the naming contract offline in the existing Python gate.

**Non-Goals:**

- Changing instance types, instance limits, Worker names, routes, Queues, R2, or
  Durable Object migrations.
- Running any Cloudflare mutation, including deleting the orphaned application.

## Decisions

### Literal per-environment names instead of Wrangler's derived default

Wrangler 4.128.0 (pinned in `cloud/package-lock.json`) has no variable or
templated container name; `--var` overlays only `vars`. When `containers[].name`
is omitted, its config validation (`validateContainerApp` in
`wrangler-dist/cli.js`) derives `<worker name>-<class_name>` lowercased from the
configuration file's Worker name and appends `-<environment>` only for named
environments, which would also be environment-scoped. Explicit literals are
chosen because the deploy workflow parses `containers[0].name` from the
checked-in configuration, the derived form ignores a CLI `--name` override (the
Worker name changes while the application name does not) and changes silently
on a class rename, and the literal form keeps the existing `rvw-sandbox` stem
that operators already recognize in `wrangler containers` output.

### Resolve once, before deploying, and fail closed

The `Deploy Worker` step resolves `env.<environment>.containers[0].name` before
calling `wrangler deploy`, rejects an environment without a container entry or
whose name lacks the `-<environment>` suffix, and exports `RVW_CONTAINER_NAME`.
Both the previous-digest capture and the rollout wait use that name, so every
account-wide `wrangler containers list` read is scoped to the selected
environment's application even when sibling applications exist. The previous
fallback to the top-level entry could have waited on `rvw-sandbox-dev` and
never observed the deployed application.

### Test the resolver the workflow actually runs

The Python test extracts the embedded resolver from the workflow YAML and runs
it against `cloud/wrangler.jsonc` for `spike`, `prod`, and an environment
without containers. This keeps the workflow logic and the test from drifting.

## Risks / Trade-offs

- [Renaming creates a new application] → The next `spike` deploy creates
  `rvw-sandbox-spike`; the old `rvw-sandbox` application keeps running until
  the deployer deletes it. Documented in the runbook and context; no automatic
  deletion.
- [A future environment forgets its container entry] → The workflow fails
  before deploying instead of reusing another environment's application.

## Migration Plan

1. Merge and release; deploy `spike`, which creates `rvw-sandbox-spike` bound to
   the existing spike Durable Object namespace.
2. Verify `/healthz` and a review on `spike`, then delete the orphaned
   `rvw-sandbox` application and its obsolete image tags with the documented
   `wrangler containers` commands.
3. Deploy `prod`, which creates `rvw-sandbox-prod` fresh. Rollback is a
   redeploy of the previous tag, which recreates the shared name and therefore
   only works while no other environment holds it.
