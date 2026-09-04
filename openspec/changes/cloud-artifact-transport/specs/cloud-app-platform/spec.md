## ADDED Requirements

### Requirement: A1 artifact reads use a supported text transport

Every A1 artifact persisted by the Worker MUST be requested as UTF-8 text using
an encoding supported by the pinned `@cloudflare/sandbox` SDK's default
transport. JSON, Markdown, environment, and log artifacts MUST NOT request the
RPC-only binary `none` encoding. An artifact that is available in the Sandbox
MUST reach its deterministic R2 key before Sandbox destruction unless its own
read or R2 write fails, and one unavailable diagnostic artifact MUST NOT prevent
best-effort persistence of the others.

#### Scenario: Terminal review has text artifacts

- **WHEN** the Sandbox process terminates with UTF-8 result and diagnostic files
- **THEN** the Worker reads them without requesting binary transport and stores
  every available artifact under `jobs/<job_id>/<artifact_name>`

### Requirement: A1 terminal process failures are observable

For every terminally observed A1 review process, the Worker MUST attempt to
persist SDK-captured stdout and stderr as `run.log`, and MUST persist a
`process.json` object containing `exitCode`, `signal`, `durationMs`, and
`command`, before parsing review result artifacts or destroying the Sandbox. It
MUST also persist the container's printenv-style redacted environment snapshot
when available. When a required result artifact is missing, the neutral Check
Run summary MUST include the process exit code, duration, and approximately the
last 20 stderr lines after filtering credential-shaped content matching
`Bearer`, `token`, or `key=` case-insensitively.

#### Scenario: Review process exits before producing a result

- **WHEN** the SDK reports a terminal process but required review artifacts are
  absent
- **THEN** R2 retains the available log, process, and environment diagnostics
  and the neutral Check Run identifies the exit code, duration, and filtered
  stderr tail

### Requirement: A1 auto invocation is self-contained

The A1 review command MUST identify its target using the full pull-request URL
already authenticated by the webhook message, MUST run from the target
checkout with the adjacent verified checkout supplied by `--repo-dir`, and the
image MUST provide a versioned fallback auto policy at rvw's existing external
policy path. A repository policy loaded from the target base revision MUST
continue to take precedence over that fallback.

#### Scenario: Reviewed repository has no auto policy

- **WHEN** the target base revision contains no `.rvw/policies/auto.yaml`
- **THEN** A1 proceeds with the image's versioned fallback policy without an
  external registry mount or a redundant repository-name API lookup
