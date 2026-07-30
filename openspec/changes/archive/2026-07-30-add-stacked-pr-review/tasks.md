## 1. Behavioral Regression Tests

- [x] 1.1 Add parsing and planning tests for ordered positive PR numbers,
  duplicates, cross-repository members, broken direct edges, and stale anchors.
- [x] 1.2 Add presence adjudication tests for majority voting, missing output,
  evidence coercion, all-invalid retry, expanded context, and final uncertainty.
- [x] 1.3 Add lineage transition tests for still-present, fixed, regressed, and
  unresolved histories.
- [x] 1.4 Add strict stack-store tests for safe run IDs, partial member-run
  persistence, artifact validation, and complete-run requirements.
- [x] 1.5 Add stack-report tests that separate member-local findings from
  stack-tip lineage state.
- [x] 1.6 Add CLI tests for plan JSON, sequential member review, dry-run
  publication without network, and full anchor revalidation before execute.
- [x] 1.7 Run the focused tests and confirm the new behavioral assertions fail
  before implementation.

## 2. Shared Pipeline Refactor

- [x] 2.1 Extract reusable pipeline artifacts, stage execution, artifact
  loading, and active-lane helpers from `cli.py`.
- [x] 2.2 Keep `review`, `report`, `auto`, and `gate` behavior and test seams
  unchanged while switching them to the extracted implementation.

## 3. Stack Resolution and Persistence

- [x] 3.1 Implement strict stack schemas, ordered PR parsing, GitHub resolution,
  same-repository/open/unmerged checks, and direct base/head edge validation.
- [x] 3.2 Implement immutable manifest creation, full-chain revalidation,
  detached member checkout orchestration, and safe cleanup.
- [x] 3.3 Implement strict file-first stack storage and incremental member-run
  references.

## 4. Review and Presence Adjudication

- [x] 4.1 Run the common review pipeline once per member in order and save its
  ordinary run reference before continuing.
- [x] 4.2 Extract actionable origin claims from each completed member without
  matching finding IDs across runs.
- [x] 4.3 Implement batched descendant presence voting, bounded retry,
  evidence coercion, expanded-context rechecks, and persisted observations.
- [x] 4.4 Derive deterministic lineage summaries for still-present, fixed,
  regressed, and unresolved histories.

## 5. Reporting, Publication, and CLI

- [x] 5.1 Render deterministic stack metadata, member-local summaries, lineage
  timelines, tip state, and coverage into `stack-report.md`.
- [x] 5.2 Add body-only COMMENT payload construction and dry-run/execute
  publication for the tip PR.
- [x] 5.3 Register `rvw stack plan`, `rvw stack review`, and
  `rvw stack publish` with strict options and machine-readable output.

## 6. Specification and Documentation Sync

- [x] 6.1 Keep stack-review, operation-modes, and reporting specifications
  synchronized with the implemented behavior.
- [x] 6.2 Add concise README usage and artifact examples for the three stack
  commands and document the explicit-list MVP boundaries.

## 7. Verification

- [x] 7.1 Run focused stack and existing CLI/publish/gate regression tests.
- [x] 7.2 Run `uv run ruff check .` and `uv run ruff format --check .` as bare
  commands.
- [x] 7.3 Run `uv run ty check` and `uv run pytest -q -m "not live"` as bare
  commands.
- [x] 7.4 Run `openspec validate --specs`, inspect the final diff, and confirm
  every implemented task is complete.
