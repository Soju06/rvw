# Reporting context

## Purpose and scope

This capability makes the review inspectable before any network action and translates persisted artifacts into a localized diagnostic Markdown report and GitHub COMMENT review. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- Agentic receipt verification adds uncovered counts and canonical hunk IDs to ordinary and gate coverage evidence. Agentic reports omit the inline-only diff-budget summary.
- ADR-012 makes the file the artifact of record. JSON stage files allow REPORT and publish to be rerun from a run ID without rerunning model discovery.
- 2026-08-12: Same-target starts within one second reproduced `FileExistsError`, motivating microsecond run IDs with bounded collision regeneration.
- The coverage table makes a zero-finding valid lane distinguishable from an all-INVALID lane and from a lane that never activated.
- Persisted coverage keeps exact replica-chunk entries for fail-closed validation, while the report derives readable per-lane dispatched and valid totals. Diff-budget output also exposes the number and file placement of prompt chunks.
- `run.json` is the shared strict status contract for persistence, CLI JSON, and Markdown. It records running, complete, degraded, or failed state, structured failed-lane executions, exact coverage totals, an optional run-level infrastructure error, and the immutable build identity that produced the run.
- The localized diagnostic synthesis section accepts an operator-written override or the retained synthesis overview and first action. Finding identity, votes, evidence, folds, coverage, and diff-budget accounting remain machine-generated.
- PR #1119 supplied concrete scale: 39/39 discovery runs produced 21 findings, merge produced 13 groups, and folds rendered five review items. DISCOVER took about 410s and ADJUDICATE about 197s.
- That run excluded 2,846,073 generated characters (about 2.84 MB) and reviewed 26,195 source characters, making the exclusion accounting a material report fact rather than a hidden prompt optimization.
- One rejected inline anchor causes GitHub to reject the entire review with 422. Bulk body fallback bounds publication at two API calls instead of probing N comments.
- Gate verdicts are rendered from persisted typed artifacts. Structured JSON retains public finding identity, dispositions and provenance; the publication view retains actionable findings and human reasons.
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

- Report headings and prose labels come from complete Korean/English catalogs selected by the presentation snapshot. Missing configuration defaults to English.
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
- Publication derives its selected findings from structured artifacts, so editing diagnostic report headings does not change finding selection.
- A run can legitimately lack `outcome.json`; the report then renders findings as unadjudicated and publication creates no inline comments.
- A degraded run can retain valid findings; every report and machine summary marks those results partial and keeps normalized reasons and available diagnostics for the failed executions.
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
  "body": "...human publication content...",
  "comments": [
    {"path": "src/a.py", "line": 12, "side": "RIGHT", "body": "..."},
    {"path": "src/b.py", "line": 8, "side": "RIGHT", "body": "..."}
  ]
}
```

If that call returns 422, rvw makes one final call with no `comments` array and appends both items beneath the localized anchor-fallback heading in the body.

## Historical deltas

ADR-012 specified a pre-publication target guard (`state=open`, matching head, not merged, not BEHIND/DIRTY). No such revalidation exists in `publish.py` or the publish CLI, so it is intentionally absent from the normative spec and remains a documented failure mode. Historical text also described all anchorable findings generally; the implementation publishes only CONFIRMED groups inline.

Stack publication closes the stale-anchor gap only for its composed command:
all captured base/head refs and SHAs and every direct edge are checked before
`--execute`, and the review payload names the captured tip commit. Standalone
ordinary `publish` retains the historical behavior described above.

## Shared result evidence (2026-09-05)

The `/tmp/rvw-surfaces-analysis.md` audit at v0.11.5 (`613201f`) found three incompatible artifact lifetimes: host retained stage directories; Actions deleted `/tmp` with its container and uploaded nothing; App copied four stage names by parsing stdout and exported seven hardcoded names. `target.json`, `run.json`, and runtime subtrees were omitted (`.github/workflows/rvw-review.yml:62–75`, `cloud/worker/src/review-job.ts:130–150,709–730`, `cloud/worker/src/artifacts.ts:1–17`, baseline lines). The explicit artifact directory and recursive file manifest remove the stdout/copy dependency and retain partial stages and runtime evidence.

App also independently counted findings/coverage using a maximum of two totals and did not reject zero VALID coverage (`cloud/worker/src/review-job-contract.ts:116–195`, `cloud/worker/src/review-job.ts:178–204`, baseline lines). Python `summary.json` now supplies lane counts, uncovered lane-hunks, merged finding severity counts, adjudication verdict counts, policy-blocking identifiers, and common Markdown for both adapters. Empty counts require interpretation alongside `process.json`; they cannot certify successful execution. Manifest self-size is stabilized before final bytes are written.

## Locale catalogs (2026-09-07)

The owner requested first-class i18n after the publication audit found Korean renderer headings combined with model explanations in multiple languages. Python catalogs own ordinary report, publication, gate, and stack chrome; Worker catalogs own bootstrap and terminal check chrome. Catalog migration preserves diagnostic content selection. Key parity, formatting argument compatibility, and a renderer Hangul-literal scan catch drift. The configured locale selects chrome; it does not translate code quotations, identifiers, or finding facts.

## Human publication split (2026-09-07)

The publication audit found run identifiers, SHA/timestamp headers, finding identities, replica votes, fold detail, coverage/budget tables, and generator footers reaching GitHub through diagnostic Markdown. The owner requested a separate human view. `report.md` remains diagnostic evidence, alongside the original structured stage files; publication is reconstructed from their findings rather than transformed by stripping report sections. It retains source locations, localized severity, short lane rule tags, titles, impact/correction, verbatim evidence, and configured footer. Rejected findings are absent. Uncertain findings remain separate and partial coverage has a short honest disclosure.

Diagnostic summary severity counters continue to include all merged groups. The localized human completion sentence counts confirmed blockers and confirmed warnings/suggestions only, and its coverage sentence counts distinct uncovered regions rather than summing repeated lane-hunk receipts. The Worker consumes that Python Markdown without recounting. Structured lane counters and policy blockers remain available in summary JSON and collapsed check text. Gate publication retains PASS/BLOCK and disposition reasons while JSON preserves actor and inheritance provenance. Stack diagnostic reports retain origin runs and timelines; stack publication focuses on findings and current presence.

## Publication locale enforcement (2026-09-07)

The locale gate evaluates rendered ordinary, inline, fallback, gate, and stack documents together before publication. It excludes code fences, inline code, URLs, path/identifier tokens, numbers and punctuation, then skips prose with fewer than 12 letters. Korean requires at least 60 percent Hangul; English requires at least 90 percent Latin and zero Hangul. Ambiguous language fails closed.

One prose-only rewrite uses the existing tool-less runtime with a 60-second deadline and exact segment-count validation. Immutable Markdown framing, finding count, severity/verdict labels, anchors, rule tags and evidence fences are compared after reconstruction. A failed rewrite leaves original diagnostic artifacts intact; without opt-in it removes any stale publish payload and records publication_language_mismatch. Explicit CLI/policy fallback uses the original prose and records language_fallback_used. The publication.json artifact records rewrite attempts separately from adjudication outcome.json.

## Unfinished rule sets and phase walls in the check (2026-09-07)

bori#1744 completed as a degraded review with two dead lanes, yet the check summary could only say that 13 changed regions were not reviewed while the collapsed details carried `lanes.uncovered: 26`; neither number was labelled and the reader could not tell that the two counts describe the same 13 hunks seen by two lanes, nor which lanes had failed, nor that four 600 s waves were the whole story. The human summary now adds one catalog sentence naming the unfinished rule sets by their verbatim lane identifiers (ko `검토를 완료하지 못한 규칙 묶음 {n}개: {lanes}.`, en `Rule sets that did not finish: {n} ({lanes}).`), and `summary.json` carries `lanes.uncovered_regions` beside `lanes.uncovered`; the Worker labels the latter `lane_hunk_receipts` in check text and adds `failed_lanes` and `wave_wall_seconds`.

Lane identifiers are Latin tokens such as `correctness` or `security-exposure`, which the language gate would otherwise score as English prose; a Korean summary naming several lanes fails the 0.6 Hangul threshold on exactly the degraded runs it describes. The gate therefore accepts the failed lane identifiers as protected literals in the check itself (the rewrite path already had the concept), consistent with the existing exclusion of identifier tokens. Identifiers are not wrapped in code spans because the owner asked for verbatim ids in the sentence and the sentence is also consumed as plain check summary text.

## Living review threads (2026-09-08)

Every rvw run used to post a fresh set of inline COMMENT threads and never resolved one, so on a consuming repository whose ruleset requires review-thread resolution each thread became manual click work before merge, including threads for findings the author had already fixed. The owner decided that rvw's own threads must behave as living threads. Identity comes from an invisible marker appended to each inline body (`<!-- rvw:v1 fp=<16 hex> rule=<rule> lane=<lane> -->`) and to each review body (`<!-- rvw:v1 review head=<sha> event=<EVENT> -->`); the fingerprint digests rule, path, and normalised adjudication evidence, never line numbers, so an unrelated edit above the flagged code keeps the identity while a change to the flagged code changes it. Evidence is model-written and will often differ between heads, so the fingerprint is a fast path; the line-mapping and unique-pair steps carry the common case.

A pre-implementation review by three independent readers changed the design in four ways that are now normative. GitHub names an App differently in its two APIs (GraphQL `Bot.login` is the bare slug, REST `user.login` carries `[bot]`), so identity is matched with the suffix stripped and the actor type checked, and every review body carries a marker so a personal-token user's hand-written reviews are never mistaken for rvw's. Threads are resolved only after the replacement review was created, because a resolution before a failed write would leave a live finding with no gating thread. "The lane was valid" is not evidence that the lane looked at the thread's region: adjudication may return UNCERTAIN, discovery is not deterministic on a same-head rerun, and dead chunks leave hunks uncovered. Resolution therefore also requires that the thread's region changed between heads (GitHub's `isOutdated`, a deleted or edited original line, or the path leaving the diff), that the mapped line's hunk is covered by the lane, that the thread was not created on the current head, and that no other identity replied; a live thread whose finding simply was not re-reported stays open as `skipped_unverified`. A degraded or failed summary, language fallback, unknown identity, or a failed read clamps everything merge-ward: matched threads are still reused, but nothing is resolved or dismissed.

Findings are never hidden. A finding matched to an existing thread is not posted inline again but stays in the review body under its section, so the count sentence and the body agree; ambiguous groups behave the same. The compare API only diffs from the merge base and returns header-less patches, so it is accepted only when the merge base is the thread's original commit, with `--- a/` and `+++ b/` headers synthesised; a rebased history is an unavailable mapping, which can only leave threads open. Recorded facts (`summary.publish`) name every thread by outcome so a wrong decision can be audited from the check text; `report.md` is untouched.

## Review event as repository policy (2026-09-08)

The owner decided that the GitHub review event is organisation policy. On the measured consuming repository the `main` ruleset requires one approving review, code-owner review, `required_review_thread_resolution: true`, `dismiss_stale_reviews_on_push: true`, `require_last_push_approval: true`, and three unrelated required status checks; a COMMENT review is invisible to that gate, the rvw check run is not a required check, and the only merge-visible effect of a review was the manual resolution of every inline thread. COMMENT therefore stays the default so nothing changes for a repository that has not decided otherwise, while `publish.on_block: request_changes` gives a repository a merge-blocking signal that `dismiss_on_pass` lifts again on the next clean head. APPROVE is double-gated (`on_pass: approve` plus `approve_requires_explicit_opt_in: false` in the same base-ref file) because a bot approval never satisfies code-owner review, may count toward `required_approving_review_count`, and, since GitHub defines `require_last_push_approval` as approval by someone other than the pusher, may satisfy that rule as well; the consuming repository owns that risk.

Every uncertainty clamps to COMMENT and disables dismissal and resolution: no policy verdict, a degraded or failed run, language fallback, unknown identity, a failed or truncated read, or a policy that could only be read from the run's own snapshot (the run directory is writable by full-access lanes in the App, so `rvw publish --run` re-reads the base ref locally or through the contents API and trusts the snapshot only for COMMENT). Payloads pin `commit_id` to the reviewed head and carry a review marker, which makes same-head idempotency exact and lets dismissal touch only rvw's own reviews under a personal token whose login is a human's. A rejected dismissal is re-read and counted only when GitHub reports `DISMISSED`, because HTTP 422 also covers "not permitted" and "wrong state". When the live head has moved past the reviewed head, nothing is written and `publication_skipped: head_moved` closes the pre-publication guard that ADR-012 had asked for and the earlier context recorded as absent.

The earlier "no network call" wording for dry runs is narrowed to "no GitHub write": `rvw publish --run` plans thread reconciliation and dismissal from read-only calls, and those reads are tolerated failures; `review` and `gate` dry runs still make no call at all.

## Reader-first synthesis (2026-09-09)

The ordinary publication opens with an artifact-derived overview and first action, then the catalog outcome paragraph. A posted inline finding also gets a short body entry with title, source location and consequence; unanchored and reused-thread findings retain full body explanations. Failed synthesis keeps the earlier full finding shape while fixing the body omission independently. This makes summary counts and visible body sections agree.

Synthesized full explanations omit the duplicated adjudication reason and collapse unchanged evidence under localized details. Diagnostic report.md still retains reasons and all prior sections; only its synthesis content has new precedence (operator file, retained overview/action, neutral placeholder). Marker construction, fingerprints, reconciliation and the language rewriter remain unchanged. See [synthesis context](../synthesis/context.md) for evidence, bounds and limitations.

## Repository publication controls (2026-09-10)

The owner principle is that choices a consuming repository could reasonably make differently belong in `.rvw/`. The publication subset of the hardcode audit includes two synthesis defects from #95: its universal language example named a Gmail inventory error copied from a bori fixture, and its blanket vocabulary ban rejected the bori #1772 discovery-domain explanation even though finding paths name `life-gmail-discovery-reconciliation`. The generic language example now demonstrates Korean prose with unchanged English identifiers in backticks; repository examples follow it. Source occurrences establish domain vocabulary for that review, and allowed terms offer a repository escape hatch without relaxing literal fidelity.

The anchored presentation snapshot owns `voice.examples`, `voice.allowed_terms` and `synthesis.enabled`; the anchored auto policy owns channels, check conclusions and inline placement. Missing keys preserve existing defaults. Explicit channels take precedence; legacy `publish_state: none` maps to checks only when channels are absent. Disabling checks still terminalizes the mandatory bootstrap check as neutral. Invalid/infrastructure/deadline outcomes cannot be configured to succeed.

Inline selection applies the severity floor, then a highest-severity cap with finding-key ties. Selection precedes living-thread reuse, so reused candidates can reduce newly posted comments below the cap. Body-only findings retain their full explanation. Body-only findings still participate in identity matching, preventing a placement change from being mistaken for fix evidence; their matched threads are excluded from reuse and write plans; historical disappeared findings retain the existing fix-proof rules. `threads.resolve_on_fix` and `threads.reuse_open_thread` apply within that boundary. A zero cap selects no inline candidates. The channel and placement facts remain available in summary artifacts and enabled check details.

Operator examples and all defaults are documented in [auto policy controls](../../../docs/auto-policy.md). The active change is [repository-publication-controls](../../changes/repository-publication-controls/proposal.md).
