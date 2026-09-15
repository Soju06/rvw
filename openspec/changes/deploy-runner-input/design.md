## Context

See [proposal.md](proposal.md) for the deployment failure motivating this change.
The workflow currently has one deploy job with a literal runner label.

## Goals / Non-Goals

Preserve the existing default and let callers select one available runner label.
Array and group selection are outside this input's contract.

## Decisions

Use `${{ inputs.runs_on }}` directly. `fromJSON` rejects bare label strings and
would require a different consumer contract. Keep the exact optional string
schema and document a Blacksmith example in `cloud/README.md`.

Use an offline contract regression check in `/tmp` before and after the change,
because this task prohibits Python file changes in the repository. Run the
required repository gates plus actionlint and the neutrality guard.

## Risks / Trade-offs

A caller-selected label must identify an available runner capable of executing
the deployment steps. Existing callers retain `ubuntu-latest`; consumers opt in
by pinning a workflow revision containing this input and adding `with.runs_on`.
