## Context

Runtime work is bounded in four separate execution helpers: the shared discovery dispatcher, adjudication, sampling, and stack presence adjudication. Ordinary review, target-mode gate, auto, and stack review enter discovery and adjudication through the shared pipeline, while sampling and stack presence add direct execution paths. See `proposal.md` and `context.md` for the operational motivation.

## Goals / Non-Goals

**Goals:**

- Keep one concurrency value for every runtime wave initiated by a CLI invocation.
- Preserve the public callable defaults for callers outside the CLI.
- Reject invalid capacities at both the Typer boundary and public async callable boundaries.

**Non-Goals:**

- Change replicas, retry waves, deadlines, voting, runtime schemas, or account admission policy.
- Add runtime work to the currently stubbed `run` or `adjudicate` commands.
- Persist concurrency in report or run schemas.

## Decisions

### Use one shared default constant

Define the value 8 once beside the shared dispatcher and use it as the default for discovery, adjudication, sampling, stack presence adjudication, and CLI options. This avoids another drift between independent semaphore sites. A CLI-only constant was rejected because non-CLI callables also require the safer default.

### Thread concurrency beside replicas

Follow the existing replica path from each Typer command through its async helper and the shared pipeline. The shared pipeline passes the value to both discovery and adjudication; stack review additionally passes it to presence adjudication, and sample passes it directly to sampling. Separate per-stage CLI options were rejected because they add operator complexity without an identified need.

### Expose the option on commands capable of runtime work

Add the option to `review`, `auto`, `gate`, `stack review`, and `sample`. A resumed `gate --run` accepts but does not use the value because it executes no runtime work. The exposed `adjudicate` command remains a stub and therefore does not receive an inert option.

## Risks / Trade-offs

- [Lower capacity can increase wall time when gateway capacity is available] → Operators can explicitly raise `--concurrency` based on account capacity.
- [A threaded path can accidentally omit one stage] → CLI capture tests and callable-level propagation tests cover ordinary, sampling, and stack paths.
- [Gate resume accepts an option it does not consume] → Keep one stable command surface; document the contract in terms of waves actually started.

## Migration Plan

Ship the new default and option without artifact migration. Rollback consists of restoring the prior default and removing the option plumbing; persisted runs remain compatible because concurrency is not stored in their schemas.
