# Reporting context

## Purpose and scope

This capability makes the review inspectable before any network action and translates persisted artifacts into a Korean Markdown report and GitHub COMMENT review. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- ADR-012 makes the file the artifact of record. JSON stage files allow REPORT and publish to be rerun from a run ID without rerunning model discovery.
- The coverage table makes a zero-finding valid lane distinguishable from an all-INVALID lane and from a lane that never activated.
- Persisted coverage keeps exact replica-chunk entries for fail-closed validation, while the report derives readable per-lane dispatched and valid totals. Diff-budget output also exposes the number and file placement of prompt chunks.
- Only `## 종합` is author-written. Finding identity, votes, evidence, folds, coverage, and diff-budget accounting remain machine-generated.
- PR #1119 supplied concrete scale: 39/39 discovery runs produced 21 findings, merge produced 13 groups, and folds rendered five review items. DISCOVER took about 410s and ADJUDICATE about 197s.
- That run excluded 2,846,073 generated characters (about 2.84 MB) and reviewed 26,195 source characters, making the exclusion accounting a material report fact rather than a hidden prompt optimization.
- One rejected inline anchor causes GitHub to reject the entire review with 422. Bulk body fallback bounds publication at two API calls instead of probing N comments.
- Gate verdicts are rendered from persisted typed artifacts rather than handwritten aggregate prose. Their finding table retains the public group key and disposition even when a CONFIRMED finding is also emitted as an inline comment.
- Stack runs keep a separate strict manifest, incremental ordinary member-run
  references, lineage observations, and deterministic Markdown report. Partial
  member references survive operational failure, while only a complete run can
  produce a publish payload.
- Stack publication is body-only because origin claims span different diffs.
  Dry-run reads artifacts without GitHub access; execute mode revalidates every
  member and direct edge before its single tip COMMENT request. Both dry-run and
  execute payloads pin `commit_id` to the captured tip SHA so a push after
  revalidation cannot move the review onto an uncaptured head.

## Constraints

- Reports are rendered in Korean headings and prose labels.
- Pattern folding applies only when every member is included in the rendered verdict subset.
- Only CONFIRMED, anchorable, line-bearing groups become inline comments.
- Dry-run results use the same `commented` state model even though no review URL exists.
- Publication uses `gh api` and expects the response JSON to contain `html_url`.
- Stack artifacts share the configured run root with ordinary runs but use
  `rvw-stack-*` IDs and reference ordinary run IDs instead of copying their
  stage artifacts.

## Failure modes

- Ordinary `publish` can still use a moved PR head; `gate` closes this failure mode by revalidating both base and head before reaching publication.
- GitHub errors without a recognizable status code cannot trigger the 422 fallback.
- If the report heading structure is manually changed, body removal for inline findings may not find `## 확정 발견 (CONFIRMED)`.
- A run can legitimately lack `outcome.json`; the report then renders findings as unadjudicated and publication creates no inline comments.
- The current code has no ADR-012 pre-publication guard for open state, head match, merge state, or BEHIND/DIRTY status.
- A failed stack member leaves an intentionally incomplete directory without
  `stack-report.md`; `stack publish` rejects it rather than reconstructing or
  repeating review work. The review command prints the stack run ID immediately
  after directory creation so those partial artifacts remain discoverable.

## Concrete example

The first payload for two confirmed anchorable findings has this shape:

```json
{
  "event": "COMMENT",
  "body": "...non-inline report content...",
  "comments": [
    {"path": "src/a.py", "line": 12, "side": "RIGHT", "body": "..."},
    {"path": "src/b.py", "line": 8, "side": "RIGHT", "body": "..."}
  ]
}
```

If that call returns 422, rvw makes one final call with no `comments` array and appends both items beneath `### 앵커 실패 항목` in the body.

## Historical deltas

ADR-012 specified a pre-publication target guard (`state=open`, matching head, not merged, not BEHIND/DIRTY). No such revalidation exists in `publish.py` or the publish CLI, so it is intentionally absent from the normative spec and remains a documented failure mode. Historical text also described all anchorable findings generally; the implementation publishes only CONFIRMED groups inline.

Stack publication closes the stale-anchor gap only for its composed command:
all captured base/head refs and SHAs and every direct edge are checked before
`--execute`, and the review payload names the captured tip commit. Standalone
ordinary `publish` retains the historical behavior described above.
