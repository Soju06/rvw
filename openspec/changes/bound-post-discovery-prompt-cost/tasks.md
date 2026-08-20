## 1. Regression Tests

- [x] 1.1 Add a failing regression proving the reviewed-diff projection returns kept segments behind the exclusion header with the same exclusion report as the chunk planner.
- [x] 1.2 Add a failing regression proving an adjudication prompt omits generated-path and oversized-file segments while retaining the exclusion header.
- [x] 1.3 Add a failing regression proving an adjudication prompt's diff content equals the single planned discovery chunk's retained segments byte-for-byte.
- [x] 1.4 Add a failing regression proving a stack presence prompt omits generated-path content for the descendant diff.
- [x] 1.5 Add a failing regression proving an all-invalid adjudication retry prompt lists each prior replica's machine-readable invalid reason and that the initial prompt does not.
- [x] 1.6 Add a failing regression proving an all-invalid discovery lane-chunk replacement prompt lists that lane-chunk's prior invalid reasons while an unretried lane's prompt does not.

## 2. Implementation

- [x] 2.1 Add the reviewed-diff projection to `src/rvw/diffbudget.py` and export it.
- [x] 2.2 Build adjudication prompts from the reviewed diff in `src/rvw/adjudicate.py`.
- [x] 2.3 Build stack presence prompts from the reviewed diff in `src/rvw/stack_adjudicate.py`.
- [x] 2.4 Thread per-lane-chunk invalid reasons into the dispatcher's replacement wave in `src/rvw/dispatch.py` and render them in `src/rvw/prompts.py`.
- [x] 2.5 Thread prior invalid reasons into the adjudication retry prompt in `src/rvw/adjudicate.py`.

## 3. Specification Synchronization and Verification

- [x] 3.1 Synchronize the adjudication, discovery, and stack-review main specs and contexts with the implemented behavior.
- [x] 3.2 Inspect the final diff for scope drift, incomplete wiring, and lockfile changes.
- [x] 3.3 Run the required bare verification gates.

## 4. Self-review remediation

- [x] 4.1 Add a failing regression proving the reviewed diff states the exclusion header exactly once when a nonempty exclusion set coincides with a multi-chunk retained diff.
- [x] 4.2 Render the exclusion header from one shared helper and rebuild the reviewed diff from retained segments instead of joining chunk text.
- [x] 4.3 Record the intersection-only failure mode in the discovery context.

## Notes

Two adjudication and stack-presence test helpers previously built targets from a
bare `@@ -1 +1 @@` hunk with no `diff --git` or `---`/`+++` file header. Those
inputs cannot reach adjudication in the real pipeline, because discovery runs the
same segmentation parser first and fails closed on them. The helpers now build
valid single-file unified diffs so they exercise the production path.

An earlier reading of the doubled expanded-pass deadline as a
`MAX_DEADLINE_SECONDS` violation was withdrawn. `expose-runtime-deadline`
explicitly considered and rejected flattening it, and documents the resulting
3600-second maximum as an accepted bounded outcome, so no deadline behavior is
changed here.
