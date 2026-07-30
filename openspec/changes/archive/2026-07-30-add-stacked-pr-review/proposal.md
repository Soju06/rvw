## Why

rvw currently reviews each pull request as an independent base/head diff. In a
stacked pull-request chain, a defect introduced in an early member can be fixed
only in a later member, so an isolated review cannot tell whether the original
claim is still present at the stack tip. Operators need an artifact-backed view
of that history without weakening the existing head-specific finding identity
or publishing stale comments on every member.

## What Changes

- Add `rvw stack plan --prs <ordered-list>` to resolve an explicit same-repository
  pull-request chain, validate every direct parent/child edge, and persist all
  base/head refs and SHAs.
- Add `rvw stack review --prs <ordered-list>` to run the existing review pipeline
  independently for each member and recheck every earlier actionable finding
  against every later member head.
- Record strict `PRESENT`, `ABSENT`, and `UNCERTAIN` observations and derive
  `STILL_PRESENT`, `FIXED_IN`, `REGRESSED_IN`, or `UNCERTAIN` lineage states
  without matching head-specific hunk IDs across pull requests.
- Persist a file-first stack manifest, member-run references, lineage history,
  Markdown report, and publish payload under one stack run directory.
- Add `rvw stack publish --run <stack-run-id>`, which writes a body-only COMMENT
  payload for the tip pull request by default and revalidates every captured
  anchor before an explicit `--execute`.
- Keep automatic stack discovery, stack gating, inherited dispositions,
  per-origin pull-request comments, and inline stack comments outside this
  change.

## Capabilities

### New Capabilities

- `stack-review`: Define explicit stack resolution, immutable member review,
  cross-head finding lineage adjudication, and tip-only publication.

### Modified Capabilities

- `operation-modes`: Require stack members to compose the existing common review
  pipeline rather than introduce a second review implementation.
- `reporting`: Define stack-level file-first artifacts and body-only,
  dry-run-by-default COMMENT publication.

## Impact

The change adds stack orchestration, persistence, presence adjudication, and
report rendering modules; registers a nested `stack` Typer application; exposes
a body-only COMMENT publisher; and extracts reusable pipeline internals from
`src/rvw/cli.py`. It adds deterministic offline tests for parsing, chain and
anchor validation, lineage voting, persistence, rendering, CLI orchestration,
and publication. It does not edit the external lane registry or change ordinary
`review`, `auto`, `gate`, finding identity, disposition, or inline-publication
contracts.
