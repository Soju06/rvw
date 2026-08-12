## Why

Explicit `--inherit` has not been used in production, so repeat PR gate runs repeatedly adjudicate already-dispositioned findings and operators hand-restated prior acceptances. Gate should discover the newest eligible same-PR disposition source automatically while retaining an explicit opt-out.

## What Changes

- In fresh `rvw gate --target <pr>` mode, automatically select the most recent prior gate run for the same repository and PR that has recorded completed dispositions when neither `--inherit` nor `--no-inherit` is supplied.
- Add `--no-inherit`; explicit `--inherit` takes precedence over discovery, and combining the two is a usage error.
- Reuse the existing validated inheritance load, match, summary, provenance, and artifact path after source selection.
- Fail open with one informational message when no eligible source exists, and exclude the current run plus different targets, repositories, pull requests, and runs without dispositions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pr-gate`: Add automatic same-PR inheritance source discovery and its precedence, opt-out, qualification, ordering, and fail-open contracts.

## Impact

The gate CLI and PR-gate helper logic gain source discovery over the configured run root, with deterministic tests covering qualifying and decoy artifacts. Existing explicit inheritance matching, summary rendering, verdict provenance, and trust-boundary validation remain authoritative. Resume mode and non-PR targets are unchanged.
