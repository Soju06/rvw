## 1. Regression Tests

- [x] 1.1 Add CLI regressions proving review and target-mode gate pass one replica by default while explicit replica counts still propagate.
- [x] 1.2 Update the plan payload regression to require `replicas: 1` and the corresponding lane-by-chunk total.
- [x] 1.3 Add signature regressions proving `discover` and `adjudicate` declare one replica by default.
- [x] 1.4 Run the focused regressions and confirm the new default assertions fail before implementation.

## 2. Implementation

- [x] 2.1 Change `_PLAN_REPLICAS` and the independent review CLI default to one without altering sample defaults or replica validation.
- [x] 2.2 Change the public `discover` and `adjudicate` callable defaults to one without altering dispatch, retry, widening, or majority-vote logic.

## 3. Specification and Documentation Sync

- [x] 3.1 Update the operation-modes, discovery, adjudication, and pr-gate main specs and adjacent contexts for the single-pass default and opt-in replication policy.
- [x] 3.2 Update only README text that states the ordinary replica default.

## 4. Verification

- [x] 4.1 Run focused regression tests and inspect the diff for the declared defaults and non-goals.
- [x] 4.2 Run `uv run ruff check .` and `uv run ruff format --check .` as bare commands.
- [x] 4.3 Run `uv run ty check` and `uv run pytest -q -m "not live"` as bare commands.
- [x] 4.4 Run `openspec validate --specs` and confirm every change task is complete.
