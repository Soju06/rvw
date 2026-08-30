## Why

RVW exposes discovery replication and concurrency but does not make the full
discovery cost visible or constrain accidental high-cost execution. A
three-replica request across four active lanes started twelve initial Codex
sessions; an all-invalid wave can double that work. The adapter also inherited
the operator's ambient Codex model and reasoning effort, so the incident ran
every discovery session as `gpt-5.6-sol` with `max` effort without the RVW
command expressing that policy.

The earlier `bound-post-discovery-prompt-cost` change does not cover this
incident: all of its affected sessions stopped during DISCOVER before
adjudication began. This change supersedes the historical cost-over-quality
decision for high-cost discovery by requiring an explicit non-interactive opt-in
while preserving the incident's runtime quality profile as the initial default.

## What Changes

- Add one pure discovery planner used by plan display, execution preflight, and
  dispatch so lane/chunk/replica counts and initial prompt characters derive
  from the exact prompts that execution will send.
- Make `--discovery-replicas` the documented positive discovery option on
  `plan`, `review`, `auto`, `gate`, and `stack review`. Keep `--replicas` as a
  compatibility alias that emits a deprecation warning; supplying both is a
  usage error.
- Add a positive `--max-discovery-runs` ceiling, defaulting to 12. The
  preflight reports initial runs, the worst-case one-retry upper bound, exact
  aggregate initial prompt characters, and the selected runtime profile.
- Require `--allow-heavy-discovery` before starting discovery when replicas are
  two or greater, the retry upper bound exceeds the configured ceiling, or the
  policy uses `max` reasoning effort. `plan` remains informative and never
  needs the flag. No interactive confirmation is used.
- Introduce a typed `CodexRuntimePolicy` that pins `gpt-5.6-sol` and `max`
  effort for every Codex adapter invocation, passing the model and
  `model_reasoning_effort` override explicitly to `codex exec`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `operation-modes`: Discovery-starting commands show and enforce an explicit
  preflight, and the formal discovery option replaces the ambiguous public name.
- `discovery`: One shared planner makes initial prompt accounting and the
  one-retry upper bound exact and reusable.
- `runtime-contract`: Codex invocations carry an explicit typed model and
  reasoning policy instead of inheriting those values from ambient user config.

## Impact

This changes `cli.py`, discovery planning, the Codex runtime adapter, and
focused CLI/runtime tests. It adds small in-memory policy/preflight modules.
It changes no external lane registry documents, adjudication replica default,
deadline, persisted run schema, report schema, dependency, lockfile, GitHub
state, or actual model/effort default.

## Non-Goals

- A hard per-exec or aggregate token, turn, or tool-call cap; the Codex CLI does
  not expose such a pre-request limit. This change only controls planned run
  count, prompt characters, model, and reasoning effort.
- Usage artifacts, cancellation/resume manifests, or partial-run reuse.
- Changing the default model or reasoning effort, evaluating cheaper profiles,
  changing the default one discovery replica, or changing adjudication's three
  replicas.
- Changing external registry lane scope or dynamic-brief metadata.
