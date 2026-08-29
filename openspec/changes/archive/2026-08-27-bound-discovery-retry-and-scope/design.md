## Decisions

### Correct only output-contract failures

The retry unit remains one lane/chunk group and at most one replacement wave.
`json_parse_error` and `schema_validation_error` are the only machine-readable
reasons that a corrective retry can plausibly fix. Timeout, cancellation,
budget, spawn, completion-marker, missing-artifact, and other failures do not
repeat their full prompt wave. After the retry decision, a no-valid-output
group retains its final INVALID executions so run-level finalization marks the
review degraded or failed rather than treating it as a zero-finding PASS.

### Metadata expands compatibly; registry adoption stays external

`scope` defaults to `repository`, matching today’s whole-repository behavior,
and `requires_brief` defaults false. Code can load and display both fields
without modifying `~/.hermes/review`. A later approved registry update can set
actual lane scopes and make `dynamic/change-intent` require a brief.

`requires_brief` skips only when both operator and PR-derived brief are absent;
PR title/body remains an allowed UNVERIFIED brief. A skipped coverage row is
zero-dispatch and explicitly marked, never silently treated as a passing lane.
