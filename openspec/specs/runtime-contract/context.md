# Runtime contract context

## Purpose and scope

This capability defines the machine boundary between rvw and a model runtime. It covers schema generation, Codex invocation, artifact validation, and the general `execute_raw` seam. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- ADR-004 replaced prose parsing with strict JSON and stable hunk enrichment. A prompt that explicitly requested an outside rule still obeyed the API-level enum schema, demonstrating that structured-output enforcement dominates prompt wording.
- Chunked discovery keeps `r<replica>` as the leaf directory required by the adapter. Multi-chunk runs add an inspectable `c<chunk>` parent, while one-chunk discovery and sampling retain their previous artifact paths.
- The enum-versus-free fixture produced five findings in each condition with near-identical text. Both missed the same deep defects, so rule scope—not the ID enum—was the suppressing factor; ADR-005 added sweep coverage rather than weakening IDs.
- OpenAI strict output rejects object schemas whose `required` array omits defaulted properties. The implementation rewrites both root and item schemas so every property is required.
- The four-part validity contract prevents a zero exit or parseable partial artifact from being silently treated as PASS. On the PR #1119 smoke, all 39 discovery runs were valid; the complete discovery/adjudication walls were about 410s and 197s.
- Output loss is normalized as `missing`, `empty`, `unparseable`, or `schema-invalid`, distinct from process exits, spawn failures, and missing completion markers. Invalid results retain exit/spawn detail and artifact paths and sizes for persisted coverage and adjudication diagnostics.
- On 2026-08-27, RVW inherited `gpt-5.6-sol / max` from ambient Codex
  configuration for every cancelled discovery session. The adapter now owns a
  typed policy and passes model plus `model_reasoning_effort` explicitly. The
  default preserves that profile while a later measured change evaluates
  lower-cost profiles.
- A bounded live `codex exec --json` spike on 2026-08-27 emitted only
  `thread.started` and `turn.started` before timeout. Terminal usage events
  were therefore not adopted as a validity contract. Traditional completed
  logs retain `tokens used` followed by a CLI usage count, so usage artifacts
  remain best-effort and validity retains the four existing signals.

## Constraints

- Completion detection currently depends on the literal Codex log marker `tokens used`.
- The adapter invokes Codex without a shell and owns one POSIX process session
  per runtime execution. Its deadline cancels the process-owning task, which
  signals the full process group with TERM and escalates to KILL after five
  seconds if it has not exited. This replaced the external foreground timeout
  wrapper after a 2026-08-27 review left Codex descendants alive beyond the
  wrapper deadline.
- The process group ID is captured as soon as the new session starts. A later
  lookup can fail after the runtime leader exits while a child remains alive,
  so cleanup probes the captured group rather than treating leader reaping as
  full process-tree termination.
- A 2026-08-28 safety review reproduced a post-KILL cleanup hang: the Codex
  child was gone but the captured group probe did not clear, leaving the RVW
  parent blocked without writing `usage.json`. The post-KILL probe is therefore
  bounded to one further cleanup interval; persistence is logged and the
  original cancellation or deadline result continues.
- A real macOS teardown verification on 2026-08-28 then observed `EPERM` from
  the zero-signal probe after KILL, although the known child PID was gone. The
  probe is treated as unverified cleanup after KILL: RVW logs the condition and
  returns the original cancellation or timeout result instead of propagating
  the probe error or waiting on the runtime leader.
- Tool-less mode uses stable Codex CLI feature controls to disable shell and
  interactive tools, rules, and persisted sessions while retaining the explicit
  Sol/max model policy. A direct strict-JSON spike completed without a shell
  event; agentic mode remains only for expanded source adjudication.
- Runtime wire findings require an integer line; only enriched findings can later carry `line: null` in persisted models.
- The namespace for `/other` comes from the first rule's prefix, so mixed-prefix lane rules are poorly defined.
- Read-only sandboxing controls Codex filesystem writes but the adapter itself writes runtime artifacts.
- The local Codex CLI exposes `--model` and TOML `-c` configuration overrides;
  it does not expose a direct per-exec token, turn, or tool-call cap.
- Component token, turn, and tool-call usage can be absent; reports must not
  substitute zero for unavailable telemetry.

## Failure modes

- Codex log wording changes can classify otherwise complete runs as `no_completion_marker`.
- Spawn failures, nonzero exits, missing artifacts, JSON parse errors, and schema validation errors are distinct invalid reasons.
- A validator that raises an unexpected exception type is not normalized into an invalid result.
- Schema files are self-contained by replacing Pydantic `$defs`; future nested models need the same care.

## Concrete example

For a warning-capped lane with rules `unscoped/security` and `unscoped/correctness`, the generated finding item permits rule IDs:

```json
["unscoped/security", "unscoped/correctness", "unscoped/other"]
```

and severities:

```json
["warning", "suggestion"]
```

If Codex exits 0 and writes conforming JSON but its run log is truncated before `tokens used`, rvw records an INVALID result with `invalid_reason: "no_completion_marker"` and exposes no output to discovery.

## Historical deltas

ADR-004 said arbitrary out-of-enum IDs would be coerced to `<lane>/other`. The current implementation instead prevents them through the generated schema and rejects any value outside the declared set plus `/other`; it does not rewrite an arbitrary returned string. ADR-004 also described `Finding` as the runtime contract, while the implementation now has the narrower `RuntimeFinding`/`RuntimeLaneOutput` wire types and enriches them downstream.
