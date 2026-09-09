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
- On 2026-08-27, RVW inherited `gpt-6-astra / max` from ambient Codex
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

## Codex model and reasoning-effort override (2026-09-08)

Four consecutive production App runs on the consuming repository at a 900 s deadline (0.15.0 and 0.16.0) ended the same way: the `correctness`, `hygiene`, and `test-integrity` lanes died at the deadline on every attempt after writing that every changed region was covered and that a final evidence pass was underway, and then kept calling tools until the kill. The `tool_calls` telemetry added in 0.15.0 put the dead lanes at 35 to 94 tool commands each and the lanes that finished at 5 to 19; the 0.15.0 budget contract in the prompt (wall budget, coverage first, 40 tool calls as guidance, no remote access) changed neither number. The owner's reading is that the habit may belong to the model x effort pair rather than to the prompt wording, and asked to A/B the reasoning effort and the model against the current default before touching the lanes. Until this change the pair was one hardcoded constant, `DEFAULT_CODEX_RUNTIME_POLICY`, and every `CodexRuntime(...)` construction in the CLI took it implicitly, so a cell could not be run without a code change and nothing but `usage.json` said which policy a run had used. The normative contract is in [spec.md](spec.md) ("Codex execution is read-only and bounded" and "Policy-gated execution owns a versioned process envelope").

Precedence, per field and resolved once per command:

| Source | Model | Reasoning effort |
| --- | --- | --- |
| 1. explicit option | `--model <m>` | `--reasoning-effort <e>` |
| 2. environment (only when the option is absent) | `RVW_CODEX_MODEL` | `RVW_CODEX_REASONING_EFFORT` |
| 3. packaged default | `gpt-6-astra` | `high` |

The effort vocabulary is the nine named variants of Codex 0.152.0 `ReasoningEffort` in `codex-rs/protocol/src/openai_models.rs` at tag `rust-v0.152.0`: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `persistent`, as lowercase wire strings. The same enum also has a `Custom(String)` passthrough, which rvw deliberately does not accept: the point of the override is to run a named cell, and a typo that Codex would forward as a custom effort would silently produce an unlabelled measurement. Validation therefore happens in `resolve_codex_runtime_policy` at the command boundary, while the `CodexRuntimePolicy` value object stays permissive (any non-empty effort string) so the adapter itself is not narrower than Codex. The model has no allowlist by design; it is any non-empty string after trimming and the proxy decides whether it is served, which is what lets a `gpt-6` variant be tried without a release. A malformed option or a present but malformed variable fails closed before any runtime exists, with the message naming the source (`--model`, `--reasoning-effort`, `RVW_CODEX_MODEL`, or `RVW_CODEX_REASONING_EFFORT`) and, for the effort, the allowed values. `reasoning_summary` is not overridable and stays `detailed`.

The resolved object is passed to every runtime the command constructs: discovery (whose retry and coverage redispatch reuse the same runtime object inside `rvw.discover`), tool-less initial adjudication and agentic expanded adjudication (which reuse the runtimes the pipeline passes), the stack presence pass, `sample`, and re-adjudication. The one runtime kept on the packaged default is the publication language rewriter in `publish.py`: its 60 s prose translation is not a review runtime and letting it follow the cell would add translation quality to a measurement about lane behaviour. `usage.json` already recorded `model` and `reasoning_effort` from the runtime's policy; `RuntimeSettings` now carries both as well, so `process.json runtime.model` / `runtime.reasoning_effort` and the `model=` / `reasoning_effort=` lines of `environment.txt` name the cell, and `run` / `auto` append `--model <m> --reasoning-effort <e>` to the canonical command after `--no-output-timeout <n>`. Both fields default to the packaged values with `min_length=1`, so a legacy `process.json` loads and an empty string is rejected, mirroring the 0.15.0 `reasoning_summary` field; the Worker parser follows the same rule.

The planned A/B has four cells on the same consuming-repository pull requests: the default (`gpt-6-astra` / `max`), `medium`, `high`, and a `gpt-6` variant at its default effort. For each cell the comparison reads `summary.json failed_lanes` (dead-lane count and reasons), `usage.json tool_calls` per lane and attempt, and `summary.json wave_wall_seconds` per wave, plus the confirmed finding counts so a cheaper cell that stops exploring is not mistaken for a better one. The cell of every run is legible from its own artifacts, which is the reason the values are recorded in four places rather than only in the runtime log.

## Default reasoning effort: `high` (2026-09-09)

The A/B the override was built for ran the same day on the same consuming-repository pull request (documentation-only head, six packaged lanes, 900 s deadline, 660 s watchdog, rvw 0.16.0/0.17.0). Cells were selected through the prod App path; the packaged default was the control.

| cell | model | effort | wall | valid lanes | dead lanes | uncovered regions | adjudication | confirmed findings |
|---|---|---|---|---|---|---|---|---|
| A | `gpt-5.6-sol` | `max` | 31 min | 4/6 | `correctness`, `hygiene` | 14 | did not run | 0 |
| A2 (rerun) | `gpt-5.6-sol` | `max` | 33 min | 4/6 | `correctness`, `dynamic/goal-parity` | 14 | 126 s | 1 |
| B | `gpt-5.6-sol` | `high` | 23 min | 6/6 | none | 0 | 196 s + 333 s expanded | 4 |

At `max` two runs died on different lanes, which places the failure in the effort setting rather than in any one lane's rules; both waves ran to the 900 s cap. At `high` every lane finished inside one discovery wave (762 s), adjudication ran, and the four confirmed findings were substantive on inspection (a documentation/implementation scope mismatch, a stale reference to two deleted lane files, and two path-predicate edge cases the author can act on). `high` therefore stopped the "final evidence pass" exploration that the 0.15.0 budget contract could not, without trading away findings.

The packaged default moves from `max` to `high` on that evidence. The override surface stays as it is, so `max` remains one flag away for a repository that wants it, and the `medium` and `gpt-6` cells remain to be measured; they are cost and model explorations now rather than the fix. A single `high` run is thin evidence on its own; the default change is also what produces the replication runs, since every review from this release on is a `high` cell whose `usage.json` and `wave_wall_seconds` can be compared with the two `max` runs above.


## Default model: `gpt-6-astra` (2026-09-09)

The override surface was then used to run two more cells on the same pull request head, each deployed through the reusable deploy workflow's `codex_model` / `codex_reasoning_effort` inputs and cleared by a plain redeploy afterwards.

| Cell | Model | Effort | Wall | Valid lanes | Discovery wave | Adjudication | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B | `gpt-5.6-sol` | `high` | 23 min | 6/6 | 762 s | 196 s + 333 s | 4 |
| C | `gpt-5.6-sol` | `medium` | 8 min | 6/6 | 363 s | 21 s | 2 |
| D | `gpt-6-astra` | `high` | 3 min | 6/6 | 93 s | 16 s | 1 |

`gpt-6-astra` at `high` completed the same six lanes in about an eighth of the wall time of the legacy model at the same effort, with no lane near the 900 s deadline. The head under test is documentation-only, so the finding counts (4 / 2 / 1) say little about depth on code; C and D also published no new comments because the same head already carried the B and A₂ reviews and their findings matched open threads (`publication_skipped: duplicate_review_same_head`, `reused_thread_ids` 2 and 1), which is the living-thread behaviour working as specified.

The packaged default moves to `gpt-6-astra` with `high` unchanged. The legacy `gpt-5.6-sol` remains selectable through `--model`, `RVW_CODEX_MODEL`, or the deploy input, and the tests that demonstrate the override precedence name it for exactly that reason: an override in a test must differ from the packaged default or the assertion is vacuous. If review depth on code pull requests regresses, the first comparison is `gpt-5.6-sol` at `high` on the same head through the deploy input; the settings API must not be used for that (it detaches the container application).
