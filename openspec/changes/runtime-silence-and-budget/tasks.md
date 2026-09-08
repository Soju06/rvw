## 1. Cancel silent runtimes and request reasoning summaries

- [x] 1.1 Add failing runtime tests: a fake process that writes its banner and goes silent is killed at N with reason `no_output_after:<N>s` and reaped; a process that writes a byte every N/2 is not killed; a process that goes silent past the deadline boundary is classified `exit_nonzero:124`; cancellation during the watchdog leaves no zombie and records `canceled`; argv carries `model_reasoning_summary`.
- [x] 1.2 Implement `_spawn_with_watchdog`, the `no_output_seconds` runtime option (`--no-output-timeout`, `RVW_NO_OUTPUT_SECONDS`, default 660), the policy summary flag, and the `RunUsage` field; record the option on `RuntimeSettings`, `process.json`, and `environment.txt`; regenerate the process schema resource; accept the new runtime fields in the Worker parser.
- [x] 1.3 Add the runtime-contract, adjudication, and operation-modes deltas and update the main specs and context, then commit feat(runtime): cancel silent runtimes with a no-output watchdog and stream reasoning summaries.

## 2. State the budget in lane prompts and record tool-call counts

- [ ] 2.1 Add failing tests: the agentic and inline prompts contain the budget sentence with the actual deadline, the agentic prompt carries the tool-call budget and the remote-access guard, a fixture `run.log` yields the expected `tool_calls` and `assistant_messages`, and persisted attempts carry both counts.
- [ ] 2.2 Implement the budget section, the log counters, `RunUsage.assistant_messages`, and the `RunAttempt` fields; pass the dispatch deadline into prompt construction.
- [ ] 2.3 Add the discovery delta and update the discovery main spec and context, then commit feat(discovery): state the time and tool budget in lane prompts and record tool-call counts.

## 3. Block remote git and non-proxy egress from review tool commands

- [ ] 3.1 Add failing tests: bash fixtures for the `git`, `gh`, `curl`, and `wget` shims in review and non-review phases; the runtime spawns Codex with `RVW_PHASE=review` and `GIT_ALLOW_PROTOCOL=none`; checkout commands run with `RVW_PHASE=checkout`; both Dockerfiles install the shims and the profile hook ahead of the real binaries; `configureCodexEgress` sets the allowlist.
- [ ] 3.2 Implement the shims, the profile hook, the Dockerfile changes, the spawn and checkout environments, and the Worker allowlist; run the shim check inside the built image.
- [ ] 3.3 Add the cloud-app-platform and runtime-contract deltas and update the main specs and context, then commit feat(cloud): block remote git and non-proxy egress from review tool commands.
