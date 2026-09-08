# Runtime contract context

## Purpose and scope

This capability defines the machine boundary between rvw and a model runtime. It covers schema generation, Codex invocation, artifact validation, and the general `execute_raw` seam. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- 2026-09-02: A Docker smoke against bori `5d4d3cb64` proved env-key authentication
  works without Codex `auth.json`, but nested read-only bubblewrap cannot create its user
  namespace. Those schema-valid responses retained 108 uncovered lane-hunks. The image
  therefore selects `danger-full-access` inside a read-only outer container, which then
  produced 6/6 valid lanes and zero uncovered hunks; host rvw still defaults read-only.
- 2026-09-01: Lane output adds a required `covered` receipt list. Discovery uses plain structured `codex exec` in the verified checkout; `codex exec review` remains unsuitable because it does not preserve the custom prompt/schema contract.
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
  event; agentic mode is used only where source exploration is required:
  checkout-backed discovery and expanded source adjudication.
- Runtime wire findings require an integer line; only enriched findings can later carry `line: null` in persisted models.
- The namespace for `/other` comes from the first rule's prefix, so mixed-prefix lane rules are poorly defined.
- Read-only sandboxing controls Codex filesystem writes but the adapter itself writes runtime artifacts.
- The local Codex CLI exposes `--model` and TOML `-c` configuration overrides;
  it does not expose a direct per-exec token, turn, or tool-call cap.
- Component token, turn, and tool-call usage can be absent; reports must not
  substitute zero for unavailable telemetry.
- `RVW_CODEX_SANDBOX` has a closed `read-only`/`danger-full-access` vocabulary; the
  latter is the measured project-container fallback, not the host default. The
  selector is applied at the shared command seam after the typed runtime mode
  selects its tool controls, so it governs both tool-less and agentic execution.

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

## Process boundary evidence (2026-09-05)

At the v0.11.5 (`613201f`) audit baseline, Python produced runtime logs and strict stage artifacts but no top-level process envelope, process log, or environment diagnostic. App generated `{exitCode, signal, durationMs, command}` directly into R2, and `signal` was always null (`cloud/worker/src/review-job.ts:632–706`, `cloud/worker/src/review-job-observability.ts:12–44`, baseline lines; `/tmp/rvw-surfaces-analysis.md`). A Python-owned version-1 process envelope now separates policy/invalid/infra classification from `run.json` engine completeness and `outcome.json` adjudication. Initialization is deliberately failure-shaped until execution finalizes, preserving truthful evidence on interruption.

The audit corrected an isolation assumption: host defaults read-only, while both container commands select danger-full-access. The root container, then launched by the since-retired Actions workflow, used read-only mounts; the App-generated script had no corresponding mount enforcement (`Dockerfile:25`, `cloud/worker/src/review-job.ts:118–128`, `cloud/worker/src/sandbox-auth.ts:115`, baseline lines). Configuration diagnostics now record the effective selector. Historical Cloudflare read-only probe success remains measurement evidence, not a claim about the production command's selected mode.

## Publication locale enforcement (2026-09-07)

Version-1 process and summary contracts now include resolved presentation plus publication_failure (nullable nonempty string) and language_fallback_used (boolean); absent legacy fields receive null/false. publication.json also records whether the bounded rewrite was attempted. Persistent locale mismatch is publication_language_mismatch under infra_failed/exit 3. The injected rewriter accepts prose slots only, uses the existing read-only runtime validity checks and a 60-second deadline, and cannot add findings, move anchors or replace quoted evidence. Its nested prompt/schema/output/log artifacts remain covered by the existing recursive manifest.

## Per-wave wall telemetry (2026-09-07)

bori#1744 took 41 minutes and the check exposed neither which lanes failed nor which phase consumed the time; `process.json` has no per-phase timers and the RCA reconstructed every boundary from `usage.json` walls and log stamps. `summary.json` now carries `failed_lanes` (lane id and final normalized reason) and `wave_wall_seconds` for seven waves: discovery initial, retry, and coverage redispatch from persisted attempt records, and adjudication initial, initial-retry, expanded, and expanded-retry from `outcome.json`, which records the longest replica wall per executed wave under its artifact label. Wave walls are telemetry appended with defaults; verdicts, retries, and the 2x expanded deadline are unchanged, and legacy summary and outcome files load with empty or null values. Each wave is a gather barrier, so its longest wall is the phase's wall clock: for #1744 the values are 600.13 (initial), 600.09 (retry), 600.16 (redispatch, now skipped for dead lanes), and 600.14 (adjudication initial).

## No-output watchdog and reasoning summaries (2026-09-08)

The measured production run reproduced a zero-byte adjudication hang on 2 of 2 adjudications with retained artifacts: both tool-less replicas r1 and r2 of the 0.13.0 run died at the 600 s deadline and replica r2 of the 0.15.0 run died at the 900 s deadline, each with a `run.log` holding only the 259-260 byte Codex banner, the verbatim prompt echo, and one newline (35,809 and 35,015 bytes in total), `cli_tokens_used: null`, and not one further byte until the kill. Codex 0.152.0 explains the pattern: the streaming POST is built with `timeout: None` (`codex-api/src/provider.rs:84`), the idle timeout only wraps `stream.next()` once a response body is streaming (`codex-client/src/sse.rs:23`), and `Reconnecting... N/5` is printed only by the stream-retry path, so a request that never receives its first byte waits until rvw kills it. On the rvw side `execute_raw` awaited `wait_for` around `_spawn`, `_spawn` blocked in `communicate`, and nothing read the log before exit, so a dead request cost the whole deadline.

The adapter now runs `_spawn` as a task and polls the combined `run.log` size every two seconds. When the size has not changed for `no_output_seconds` the spawn task is cancelled, which flows through `_cleanup_before_unwind` and `_terminate_and_reap` exactly like a deadline kill, and the run is INVALID with reason `no_output_after:<N>s`; the silence clock starts at spawn time, so a runtime that never writes a byte is killed after the same interval. A deadline expiry cancels the same task and still classifies as `exit_nonzero:124`; when `no_output_seconds >= deadline_seconds` the watchdog cannot fire first. Whichever fires first owns the classification: a deadline that expires while the watchdog's own kill is still being reaped (up to 10 s for a runtime that ignores TERM) keeps `no_output_after:<N>s`, because the adapter records that the watchdog fired before it starts the kill. A dispatcher cancellation that arrives while the watchdog is reaping is honored after cleanup completes and recorded as `canceled`; the adapter discriminates it from the shield's own `CancelledError` by the waiting task's cancel count rather than by the spawn task's state, so a cancel landing in the same loop tick as the reaped task settles is not swallowed. A kill whose terminate-and-reap itself raised (for example `EPERM` from `killpg`) is not reported as a clean kill: the failure propagates and an `OSError` classifies as `spawn_error:<Type>`, as a deadline kill did before the watchdog existed. Growth includes stderr, so a runtime printing reconnect notices is alive. `no_output_after:*` is transient: `dead_by_timeout` still matches only `exit_nonzero:124`, because a deadline kill means the lane used every second it was given while a watchdog kill means the runtime never engaged and a fresh process usually does.

The default is 660 seconds, not the 180 seconds a streaming-summary log would allow. The legitimate tool-less silences on the measured runs were 426.6 s (0.13.0 r3) and 546.6 s (0.15.0 r3, which printed one reconnect line directly before its answer), so N must exceed 546.6 s with margin today; 660 is about 20% above the longest. Codex 0.152.0 cannot be shown to stream reasoning summaries during a silent turn in `exec` mode: the human-output processor renders a `Reasoning` item only when it completes (`exec/src/event_processor_with_human_output.rs:108-117`, dispatched from `ItemCompleted` at `:290`) and handles no summary-delta notification, the JSONL processor likewise emits reasoning on completion (`event_processor_with_jsonl_output.rs:151`), the model slug already used fallback metadata with `supports_reasoning_summary_parameter: true` and `default_reasoning_summary: Auto` (`models-manager/src/model_info.rs:143-166`, applied by `core/src/session/step_settings.rs:59-61`) while the banner read `reasoning summaries: none`, and none of the 25 retained logs contains a reasoning line. A tool-less replica's long think is one reasoning item that completes immediately before the answer, so its summary cannot break the silence. Every invocation now passes `model_reasoning_summary="detailed"` explicitly and records it in `usage.json`, `process.json`, and `environment.txt`, so the banner documents the request and any summaries the backend does return grow the log; the model and reasoning effort are unchanged. At 660 s the watchdog saves 900 - 660 = 240 s on the measured 900 s hang and nothing at a 600 s deadline, where it is inert by construction.

## Tool-call telemetry from the runtime log (2026-09-08)

The Codex 0.152.0 human output processor prints a line that is exactly `exec` before each tool command (followed by the command and its working directory, a footer reporting the outcome and duration, and the captured output) and a line that is exactly `codex` before each assistant message. At exit the adapter counts those whole lines in `run.log`, after stripping a trailing carriage return, and records them as `tool_calls` and `assistant_messages` in `usage.json`; tool-less mode records zero tool calls as before, and an unreadable log leaves both unknown. On the measured production run these counts had to be extracted by hand: valid agentic lanes used 3 to 8 tool commands, the one lane that converged used 33 and then 7 on retry, and dead lanes ran 41 to 95. The caveat is that the match is textual: tool output that itself contains a bare `exec` or `codex` line inflates the count (an indented or prefixed occurrence does not match), and the counts are read from the same log whether the run was valid, invalid, or killed. They are therefore telemetry that never affects validity, discovery copies them onto persisted attempts, and nothing is enforced on them.

## Review-phase spawn environment (2026-09-08)

The adapter spawns Codex with `RVW_PHASE=review` and `GIT_ALLOW_PROTOCOL=none` added to a copy of its own environment; the rvw process never carries either value. The phase is a marker for the container images' PATH shims (`docker/shims`), which refuse remote `git`, and every `gh`, `curl`, and `wget` call, only while it reads `review`, so the same binaries serve the CLI's own checkout (`RVW_PHASE=checkout`, set by `checkout.py`'s default runner) and publication (no phase) unchanged. `GIT_ALLOW_PROTOCOL=none` closes the absolute-path bypass a PATH shim cannot: git treats the variable as a whitelist and refuses every remote transport (`https`, `ssh`, `git`, and local `file` clones) while local commands keep working, verified with git 2.34 and 2.43. Codex 0.152.0 passes the full parent environment to tool commands by default (`protocol/src/config_types.rs:207-218`, `inherit = All`), so both values reach every model-driven shell command. On a host without the shims the phase is inert and the read-only Codex sandbox already denies tool network.
