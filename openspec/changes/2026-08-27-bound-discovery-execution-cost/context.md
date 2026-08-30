# Discovery execution cost context

## Purpose and scope

This change records the operational evidence and compatibility boundaries for
preflighting high-cost discovery. Normative behavior is in the adjacent delta
specifications.

## Measured basis

- Five cancelled RVW runs on 2026-08-27 created 48 Codex sessions and consumed
  6,090,617 reported CLI tokens. Forty-two unfinished sessions accounted for
  89.7% of that amount.
- Three broad lanes accounted for about 95% of reported CLI tokens. Skipping an
  unavailable dynamic brief alone would not materially control the incident.
- An explicit three-replica discovery request across four lanes produced 12
  initial runs. The all-invalid retry rule permits 24 executions.
- The synthetic incident diff had 32 files and each lane prompt was about
  71.5 KB / 1,630 lines. First-turn model input was roughly 39k–43k tokens.
- All 48 sessions used `gpt-5.6-sol` at `max`; the adapter inherited that policy
  from ambient Codex configuration rather than recording it itself.

## Constraints

- Initial prompt characters are exactly computable before execution; retry
  feedback depends on actual invalid reason strings and is not represented as a
  fictional exact character total.
- The currently installed Codex CLI exposes `--model` and TOML `-c` overrides,
  but no direct `--max-turns`, `--max-tool-calls`, or `--token-budget` option.
- No external registry or runtime profile evaluation belongs in this change.

## Failure modes

- Computing a plan in the CLI separately from prompt construction would report
  a count that no dispatched runtime actually receives.
- Comparing a ceiling only with initial runs fails to bound an all-invalid
  retry wave.
- A TTY prompt cannot protect CI or noninteractive callers.
- Leaving model/effort implicit lets a user-level configuration change silently
  change review cost and quality for every lane.
