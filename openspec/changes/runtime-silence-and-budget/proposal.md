## Why

The measured production App review on rvw 0.15.0 at `--deadline 900` (2026-09-08) spent its three 900-second barriers on failure modes that more time cannot fix. One adjudication replica hung with zero bytes of output after the prompt echo until the deadline killed it (reproduced on 2 of 2 production adjudications with retained artifacts: both 0.13.0 replicas at 600 s and one 0.15.0 replica at 900 s), while the other replicas had answered after 160 s and 547 s; the wave waited for the hung one. The three discovery lanes that died were working, not hung: they had covered every changed region early (as early as 11% of the log), then ran 21 to 86 more tool commands of open-ended exploration without ever emitting the final schema, because the prompt never states the wall budget. One lane that had passed in 236 s on the previous head mistyped the base SHA, decided the missing ancestor was suspicious, and spent the remaining budget fetching from the remote, pulling the PR and its check runs from the GitHub API, and cloning an unrelated third-party repository, because the container runs Codex with `danger-full-access` and open egress.

## What Changes

- Every Codex runtime is raced against a no-output watchdog: when the combined `run.log` (stdout and stderr) has not grown for `no_output_seconds`, the process group is terminated through the existing cancellation path and the run is INVALID with the transient reason `no_output_after:<N>s`. The deadline race is unchanged; whichever fires first wins. The option is `--no-output-timeout` on `run`, `review`, `auto`, `gate`, and `stack review`, env `RVW_NO_OUTPUT_SECONDS`, default 660 s, recorded in `process.json`, `environment.txt`, and `usage.json`.
- `no_output_after:*` is a transient failure, not dead-by-timeout: the lane stays eligible for the ordinary retry and the single coverage redispatch, and adjudication keeps retrying only when every replica is invalid, so an early replica kill leaves the other votes intact and the wave wall becomes the slowest valid replica or `N`.
- Every invocation passes `model_reasoning_summary` explicitly and records it; the value cannot be shown to stream summaries during a silent turn, so the watchdog default stays at the legitimate-silence ceiling rather than the 180 s the summaries would allow.
- Lane prompts state the wall budget in seconds, require coverage of every changed region first and the final schema immediately afterwards, give a tool-call budget of 40 as guidance, and forbid fetching, cloning, or querying remote repositories or APIs. The runtime counts `exec` turns and assistant messages from the log at exit and records `tool_calls` and `assistant_messages` on `usage.json` and on each persisted attempt.
- Review tool commands cannot reach remote git or the GitHub CLI: both container images put PATH shims for `git`, `gh`, `curl`, and `wget` ahead of the real binaries, the runtime spawns Codex with `RVW_PHASE=review` and `GIT_ALLOW_PROTOCOL=none`, the CLI runs its own checkout with `RVW_PHASE=checkout`, and the Worker restricts sandbox HTTP(S) egress to the Codex proxy host, `api.github.com`, and `github.com` for the whole run.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtime-contract`: no-output watchdog option and reason, reasoning-summary flag, `tool_calls` and `assistant_messages` telemetry, review-phase environment of the spawned runtime, new process-contract runtime fields.
- `discovery`: budget contract in lane prompts, transient-versus-dead-by-timeout rule, redispatch eligibility of watchdog kills, attempt telemetry fields.
- `adjudication`: replica watchdog semantics and the resulting wave wall.
- `cloud-app-platform`: review-phase PATH shims in the image, the phase environment contract, sandbox egress allowlist, and the documented post-checkout gap.
- `operation-modes`: the `--no-output-timeout` option and `RVW_NO_OUTPUT_SECONDS`.

## Impact

- `src/rvw/runtimes/codex.py`, `src/rvw/runtimes/__init__.py`, `src/rvw/runtime_policy.py`, `src/rvw/cli.py`, `src/rvw/summary.py`, `src/rvw/resources/schemas/process.schema.json`, `src/rvw/prompts.py`, `src/rvw/discover.py`, `src/rvw/checkout.py`.
- `docker/shims/*`, `docker/rvw-shims.sh`, `Dockerfile`, `cloud/Dockerfile`, `docs/container-image.md`, `cloud/README.md`.
- `cloud/worker/src/review-job-contract.ts`, `cloud/worker/src/sandbox-config.ts`, `cloud/worker/src/review-contract-fixtures.ts` and tests.
- Main specs and `context.md` for the five modified capabilities.
