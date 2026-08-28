## Why

The current dispatcher repeats every all-INVALID lane/chunk group once,
including timeout and cancellation-shaped failures where repeating the same
full replica wave spends more without correcting an output contract. It also
lets a no-valid-output group flow into merge as zero findings, which can be
mistaken for an empty review rather than incomplete coverage. Finally, lane
documents cannot declare their intended code-search scope or require an
operator/PR brief before calling a dynamic lane.

## What Changes

- Retry only all-INVALID groups whose every reason is a correctable
  schema/format failure (`json_parse_error` or `schema_validation_error`).
- Fail DISCOVER closed as incomplete when any lane/chunk finishes with no valid
  output, retaining its artifacts and machine-readable reasons.
- Add `scope: diff | direct-deps | repository` and `requires_brief` lane
  metadata. Existing documents default to `repository` and `false`.
- Skip a dynamic lane with `requires_brief: true` when no operator or PR brief
  is available, recording `skipped_reason: brief_unavailable` with zero dispatch.

## Non-Goals

- Changing external registry lane documents; this needs separate user approval.
- Building a dependency resolver for `direct-deps`; scope is declarative here.
- Changing replica defaults or choosing balanced/thorough profiles without a
  golden-set evaluation.
- Implementing a hard token limit.
