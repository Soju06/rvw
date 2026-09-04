## Why

The 2026-09-04 A1 live run reached the Sandbox and authenticated both private
git and GitHub API traffic, but every artifact upload failed because the Worker
requested `readFile` binary encoding over the pinned SDK's default transport.
The review process also ended far earlier than the measured A0 review without
its captured logs or process facts reaching R2, so the terminal Check Run could
not explain the exit.

## What Changes

- Read every persisted JSON, Markdown, and log artifact explicitly as UTF-8,
  which is supported by the pinned `@cloudflare/sandbox` 0.12.9 transport.
- Capture terminal stdout and stderr plus process exit, signal, duration, and
  command before parsing result artifacts or destroying the Sandbox.
- Persist those diagnostics and an available redacted environment snapshot to
  R2 on a best-effort basis for every observed terminal process.
- Include exit code, duration, and a filtered stderr tail when required review
  artifacts are absent.
- Bypass the failing repository-name lookup by invoking auto mode with the
  already-known full pull-request URL, and install a versioned fallback auto
  policy for repositories that do not define one at their base revision.
- Record the measured transport facts and remaining early-exit hypotheses in
  the cloud platform context and runbook.

## Capabilities

### Modified Capabilities

- `cloud-app-platform`: make A1 text-artifact persistence compatible with the
  pinned Sandbox SDK and make terminal process failures observable.

## Impact

The change affects the Cloudflare Worker review job, artifact metadata and
offline TypeScript tests, plus OpenSpec and cloud operations documentation. It
does not deploy resources, change secrets, edit the external review registry,
or introduce a binary artifact transport. Repository base-revision policy
continues to take precedence over the image fallback.
