## Context

Six public runtime helpers independently default `deadline_seconds` to 600, and the Codex adapter passes that value to GNU `timeout`. Ordinary review, target-mode gate, auto, and stack review enter discovery and adjudication through the shared pipeline, while sampling and stack presence are direct runtime paths. Adjudication and stack-presence adjudication already double the selected base deadline for their one expanded pass. The earlier `lower-default-runtime-concurrency` and `split-replica-defaults` changes both listed deadlines as a non-goal. See `proposal.md` and `context.md` for the operational motivation and measured basis.

## Goals / Non-Goals

**Goals:**

- Keep the existing 600-second behavior when an operator does not pass `--deadline`.
- Carry one operator-selected base deadline to every runtime path initiated by a command.
- Bound the CLI value from 1 through 1800 seconds before any runtime work starts.
- Use one shared default constant for all six callable defaults and the five CLI options.

**Non-Goals:**

- Change replicas, concurrency, retry waves, widening, voting, runtime schemas, or host-slot admission.
- Change the existing doubled deadline used by expanded adjudication and presence passes.
- Add runtime work or inert options to the currently stubbed `run` and `adjudicate` commands.
- Persist deadline values in run or report schemas, change the external registry, or add dependencies.
- Impose the CLI ceiling on direct Python callers, which retain their existing positive-value validation contract.

## Decisions

### Use shared default and ceiling constants

Define `DEFAULT_DEADLINE_SECONDS = 600` and `MAX_DEADLINE_SECONDS = 1800` beside the shared concurrency default. Replace all six callable default literals with the shared default and use both constants at the Typer boundary. Duplicating the default in the CLI was rejected because public Python callables also need a stable, drift-free default.

### Bound operator input at the CLI boundary

Declare `--deadline` with Typer minimum 1 and maximum 1800 on `review`, `auto`, `gate`, `stack review`, and `sample`. Those are exactly the commands that can start runtime work; a resumed `gate --run` accepts but does not consume the value because it starts no runtime wave. Direct Python callers continue to accept any positive value so this CLI addition does not narrow their existing API contract.

### Thread the deadline beside concurrency

Follow the existing concurrency path through each command helper. The shared `execute_pipeline` function passes the base deadline to both discovery and ordinary adjudication. Stack review additionally passes it to descendant presence adjudication, while sample passes it directly to sampling. Separate per-stage deadline flags were rejected because one invocation should have one predictable base timeout policy.

### Preserve expanded-pass derivation

Initial adjudication and presence passes receive the selected base deadline; their existing single expanded pass receives twice that value. Tests continue to use a non-default base so they fail if either propagation or multiplication is removed. Flattening expanded passes to the base value was rejected because it would silently alter established widening behavior.

### Cap the operator value at 1800 seconds

The current 600 seconds already accommodates the observed workload: the PR #1119 smoke completed 39 valid discovery runs with about 410 seconds of discovery wall time and about 197 seconds of adjudication wall time. With process concurrency no greater than eight, total discovery slot occupancy was at most `410 * 8` seconds, so mean occupancy across the 39 runs was under roughly 85 seconds. The 1800-second ceiling is three times the existing base and more than twenty times that derived mean upper bound. Because an expanded pass doubles the base, the maximum operator setting bounds one expanded runtime at 3600 seconds.

Runtime execution holds a host-global slot for its duration. Without a CLI ceiling, a value such as 18000 could occupy a shared slot for five hours and stall other rvw processes. Work that genuinely exceeds the ceiling should be divided through the existing chunked discovery path rather than pinning one runtime indefinitely.

### Record the upstream command gap

Upstream PR #15 (`fix/lane-failure-fail-closed`) implements the currently stubbed `adjudicate` command as a runtime-executing command. That branch predates the concurrency change, so it has neither `--concurrency` nor `--deadline`. A follow-up must add both when it lands.

## Risks / Trade-offs

- [A threaded path can silently omit the selected deadline] → Capture the base deadline at every command injection point and both shared pipeline stages.
- [A high deadline can delay other host-slot users] → Reject CLI values above 1800 before runtime execution and retain the host-global concurrency gate.
- [The expanded pass can exceed the visible base value] → Document and test the existing two-times derivation, including the one-hour maximum at the CLI ceiling.
- [A resumed gate exposes an unused option] → Keep one stable gate command surface and define propagation only for runtime waves actually started.

## Migration Plan

Ship the option and shared defaults without artifact migration. Rollback consists of restoring the literal callable defaults and removing the option plumbing; persisted runs remain compatible because deadlines are not stored in their schemas.
