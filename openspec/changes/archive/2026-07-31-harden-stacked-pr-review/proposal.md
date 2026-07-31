## Why

Review of the stacked pull-request workflow found three correctness gaps: member
diffs can include reverse base-only changes, lineage history mistakes numeric PR
order for caller order, and tip publication can race onto an uncaptured head.
The same review also identified four bounded reliability and recovery
improvements in presence adjudication and stack-run reporting.

## What Changes

- Resolve every stack member diff from the captured base/head merge base to the
  captured head, matching ordinary GitHub pull-request diff semantics.
- Treat manifest position as lineage order, accept non-monotonic PR numbers, and
  validate completed lineage histories against the manifest.
- Pin body-only stack review publication to the captured tip SHA with
  `commit_id`.
- Reject duplicate presence IDs, expose only short batch-local IDs to the model,
  and map those IDs back to persisted lineage IDs in-process.
- Include the previous wave's invalid reasons in an all-invalid retry prompt.
- Announce a stack review run ID immediately after its artifact directory is
  created, including on later partial failure.

## Capabilities

### Modified Capabilities

- `stack-review`: Merge-base member inputs, manifest-ordered lineages, strict
  batch-local presence identifiers, retry feedback, early recovery IDs, and
  commit-pinned tip publication.
- `reporting`: Stack publish payloads record the captured tip commit and partial
  stack runs expose their ID before model work.

## Impact

The change affects stack resolution, lineage validation, presence prompt and
output mapping, CLI progress output, body-only publication payloads, OpenSpec
contracts, and focused tests. Persisted lineage IDs remain unchanged. It does
not modify the external review registry, add dependencies, change GitHub review
event types, or address the repository-wide prompt-injection surface.
