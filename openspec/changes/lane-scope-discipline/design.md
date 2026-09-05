## Context

See proposal.md. The audit examines 48 packaged and 29 project rules. Current single-file headings already own rule IDs, while the main spec still describes the compatibility registry. Changes must stay separate from concurrent review/pipeline work.

## Goals / Non-Goals

**Goals:** align each rule with its activation domain, preserve IDs through moves, provide deterministic offline authoring checks, and reconcile the registry contract.

**Non-Goals:** runtime per-file diff filtering, semantic similarity inference, external registry mutation, a fifth policy tier, or review/pipeline changes.

## Decisions

- Keep fnmatchcase with normalized POSIX paths and optional leading `**/`; reject braces rather than implement a second pattern language. Explicit root twins remain valid documentation.
- Use directory conventions for backend ownership; omit bare language globs and ambiguous `**/api/**`, which matches frontend API clients. Scope findings to matching domain paths even in mixed diffs. Arbitrary layouts require repository lanes.
- Split test and CI integrity because they have different activation subjects. Preserve `test-ci/critical-flaw` for tests and name the extracted gate check `test-ci/fail-open-gate`. Keep unused-added in manifests; remove orphaned-remaining until package-boundary activation exists.
- Put substantive guidance beneath each moved rule heading. Language twins retain `slop/typing-bypass`, since disjoint finding locations share a defect class.
- Make `schedule_hint` the model/dispatch key. Accept legacy `cost` with a visible deprecation warning for one release, reject simultaneous keys, and keep a read compatibility property for untouched review/plan consumers.
- Mechanical lint scans the entire prompt with source offsets and explicit per-tier/domain keyword sets, narrow inline exceptions or typed frontmatter term exceptions. Scope errors fail the opted-in check. It compares project heading IDs and normalized first sentences against packaged and supplied base rules. This is not a proof of semantic scope or duplicate ownership.
- Add only the requested lint CI step. Bori Markdown is reviewed and linted using this worktree before its single authorized commit and push.

## Risks / Trade-offs

- Directory conventions cannot discover arbitrary ownership → document supported conventions and test negative frontend probes.
- Keyword checks can flag generic examples → retain narrowly explained exceptions; do not infer semantic correctness from a clean run.
- Rule IDs can have more than one language owner → document disjoint finding domains and all moves for covered-rule references.
- Removing manifest-only orphan checks reduces nominal coverage → document why pretending to cover source-only removals is unsound.

## Migration Plan

Ship heading-preserving moves and a changelog, update packaged/project metadata, keep the cost alias for one release, then remove it in a separately specified change. Retain the active change for review after verification; no external registry migration or archive is performed here.
