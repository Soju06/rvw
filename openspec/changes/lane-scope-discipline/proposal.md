## Why

The lane audit found domain rules in unconditional base lanes and predicates that activate backend checks on frontend files. Main lane-registry requirements also lag behind the implemented single-file registry.

## What Changes

- Split packaged tool, language, test/CI, and manifest checks into accurate scopes; trim duplicated and process-only clauses.
- Make leading `**/` optional for root matching and reject unsupported brace globs.
- Rename frontmatter `cost` to `schedule_hint`, retaining a warning-emitting compatibility alias for one release.
- Add mechanical scope and project/base duplicate checks to `rvw lanes lint --scope`, with explicit term exceptions and one CI step.
- Document authoring discipline, inventories, and stable rule moves; refine consuming project lanes separately.
- Synchronize the single-file registry contract and scope discipline in lane-registry.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `lane-registry`: single-file loading, activation glob semantics, scope discipline, scheduling metadata, and scope lint.

## Impact

Lane documents, loader, activation/glob matching, dispatch hint lookup, lane lint command/tests, authoring documentation, lane-registry OpenSpec, and one CI step. No review pipeline, publication policy, cloud, or external registry changes. Bori changes are limited to project lane Markdown on its existing PR branch.
