## Context

`discover()` currently reconstructs lanes, chunks, and prompts immediately
before dispatch. `rvw plan` independently recreates only lane/chunk/replica
arithmetic and stores an empty prompt in each `PlannedRun`, so it cannot report
the actual prompt size. `CodexRuntime.execute_raw()` builds `codex exec` without
`--model` or a reasoning configuration override, which leaves runtime quality
and cost dependent on the invoking user's `config.toml`.

The direct cost incident used four lanes, three discovery replicas, one chunk,
and `gpt-5.6-sol / max`. Twelve initial sessions all had about a 71.5 KB prompt;
all-invalid retry behavior permits 24 discovery executions. The exact text
added to a retry depends on observed invalid reasons, so only initial prompt
characters are knowable before execution.

## Goals / Non-Goals

**Goals:**

- Derive CLI plan, preflight, and dispatched prompts from one pure planning
  function.
- Let an operator see the bounded discovery shape before model work starts.
- Fail closed for the three explicitly identified high-cost conditions without
  relying on a terminal prompt or TTY.
- Keep today’s effective `gpt-5.6-sol / max` quality profile while making it
  visible and independent of ambient configuration.

**Non-Goals:**

- Estimate or enforce a token total before each model request.
- Persist or aggregate usage data, resume cancelled work, or alter retries.
- Add lower-cost profiles or alter existing discovery/adjudication defaults.

## Decisions

### Use a pure `DiscoveryPlan` as the one planning seam

`plan_discovery` will load active lanes, derive the effective brief, apply the
existing diff budget, and build the same `PlannedRun` prompts consumed by
`discover`. Its plan exposes lanes, chunks, budget, and initial runs. The CLI
will sum `len(prompt)` across those runs for exact aggregate initial prompt
characters, and dispatch will reuse the plan's `PlannedRun` list. A second,
partial plan implementation in the CLI was rejected because its empty prompts
are the present source of accounting drift.

### Define the ceiling against worst-case retry work

`max_discovery_runs` is a positive CLI value with a default of 12. A
preflight's initial count is the number of planned lane/chunk/replica runs; its
retry upper bound is exactly twice that count because each identity can be
retried once at most. The ceiling compares against that upper bound, not the
initial wave, so accepted invocations remain bounded even when every initial
result is invalid. The default lets a normal four-lane single-replica review
reserve at most eight discovery executions while requiring an opt-in for the
incident's 24-execution shape.

### One acknowledgement flag covers all deliberate high-cost modes

The preflight emits stable reasons when discovery replicas are at least two,
when retry upper bound exceeds the ceiling, or when the selected effort is
`max`. Any nonempty reason set requires `--allow-heavy-discovery` before a
discovery-starting command can call the common pipeline. The flag is deliberately
not inferred from TTY state and `plan` never executes model work, so it only
reports the required acknowledgement. Supplying both replica spellings is an
error rather than inventing precedence.

### Pin policy at the runtime adapter boundary

`CodexRuntimePolicy(model, reasoning_effort)` validates non-empty values and
renders the exact `codex exec` argument pair: `--model <model>` plus
`-c model_reasoning_effort=<quoted-effort>`. `CodexRuntime` owns that policy,
so discovery, adjudication, sample, and stack-presence paths all bypass ambient
model configuration. The default is deliberately `gpt-5.6-sol / max` to
preserve current review quality; choosing Terra or lower effort belongs to the
later measured-profile change.

## Risks / Trade-offs

- [Plan and execution prompts could diverge] → Build both from the same pure
  discovery plan and assert prompt-character accounting in tests.
- [A valid legacy script sees a warning] → Keep `--replicas` behavior intact
  for one release boundary, emit the warning to stderr, and reject only the
  ambiguous combination with the formal name.
- [The default max effort now needs an acknowledgement] → This is intentional:
  current quality is preserved but high-cost discovery becomes visibly opted in.
- [The 12-run ceiling is too low for a legitimate review] → An operator can
  set a positive higher ceiling and make the separate explicit acknowledgement.
- [Codex changes its configuration key] → The adapter command has a focused
  contract test and the local Codex help plus official Codex documentation
  establish `--model` and TOML `-c` overrides for this release.

## Migration Plan

Ship the alias and its warning together with the new formal option. Existing
callers using `--replicas N` retain discovery count `N` but must add
`--allow-heavy-discovery` when the preflight marks that shape as high cost.
Rollback removes the new preflight/policy and restores the former implicit
runtime command; no persisted artifact needs migration.
