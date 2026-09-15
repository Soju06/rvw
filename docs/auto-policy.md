# Repository review, publication and synthesis controls

rvw reads `.rvw/policies/auto.yaml` and `.rvw/config.yaml` from the captured base
revision. A pull request cannot change its own review settings through head edits.
Missing keys use the defaults below. Malformed presentation settings fail with
`presentation_config_invalid`; malformed publication settings fail with
`publish_policy_invalid`.

Review starts are controlled by `triggers` in the same base-ref `auto.yaml`.
Keep the judgment and publication blocks when adding these snippets. The explicit
defaults preserve all four existing automatic actions and enable human mentions:

```yaml
triggers:
  events:
    pull_request:
      enabled: true
      actions: [opened, synchronize, reopened, ready_for_review]
    mention:
      enabled: true
      surfaces: [issue_comment, pull_request_review_comment]
      allow: [OWNER, MEMBER, COLLABORATOR]
  dedupe_same_head: true
  mode: denylist
  drafts: skip
  rules: []
```

For mention-only review starts:

```yaml
triggers:
  events:
    pull_request:
      enabled: false
```

For cheaper automatic reviews that omit pushes and reopening:

```yaml
triggers:
  events:
    pull_request:
      actions: [opened, ready_for_review]
```

Mentions work in each configuration. An allowed human can comment `@<app-slug>`
or `@<app-slug> review` on the PR or an inline review thread. Matching ignores
case. Only code (inline, fenced, or indented), HTML, and blockquotes are excluded
content; strikethrough `~~@slug~~` and curly-quoted `“@slug”` remain accepted.
Blockquoting an earlier request therefore does not request another review; a
fresh unquoted mention after the quote does. Whole-token boundaries survive
Markdown formatting: `foo**@slug**` and `@slug**bot**` are rejected, while
`**@slug**`, `(@slug)`, `@SLUG`, and `[@slug](url)` are accepted. Longer usernames,
email-like tokens, and team mentions such as `@slug/review` are rejected.
Sentence suffixes remain accepted: `@slug.`, `@slug,`, `@slug?`, `@slug!`,
`@slug's`, and `@slug:`. The App derives its slug from authenticated GitHub
metadata and caches that identity across requests for five minutes. Ordinary
comments without `@` need no identity lookup or Markdown parse, regardless of
cache state. With an unexpired identity, comments without a literal
case-insensitive `@<app-slug>` also stop before API work or parsing. After expiry,
a comment containing `@` can refresh the identity before the literal precheck,
so a mention using a renamed App's new slug can be accepted. An identity lookup
failure is logged and returns 204, so the request may be lost without failing
ordinary webhook delivery.

Mentions bypass draft and rule filters, including allowlist misses, and can rerun
a completed head. A mention during an active run for **the same PR and head**
joins it. Both accepted cases receive an 👀 reaction when the token has
permission; no acknowledgment comment is posted. A replay of the same comment
stays pinned to its original PR/head even after a push and cannot request a new
run. A genuinely new comment after a push can request the new head.

Automatic starts skip an exact head that this App already reviewed for **the
same installation, repository, and PR**. The App consults that PR/head executor,
then its own completed check runs on the commit if local evidence is missing or
inconclusive. Check ownership uses the numeric App ID. Job identity is
authoritative: a parseable `external_id` (`installation:repo:pr:sha`) and any
identity recovered from structured `job_id` or `artifact_key` facts must match
the requested installation, repository, PR, and head. A contradictory identity
rejects the check even if `pull_requests[]` lists this PR. At least one job
identity must be recoverable; commit/branch association alone never suppresses
review, so ambiguous history permits a review. A completed review on a different
PR with the same SHA does not suppress this PR: its base and diff can differ.
Separate PRs sharing a commit may run concurrently.

This includes an unchanged-head Ready flip. A durable completed-review marker
survives later reruns. New checks require structured `review_completed: true`;
legacy records require completed state, a success/failure conclusion, and no
trigger skip. Legacy checks additionally require job/artifact facts matching the
requested job, valid lane evidence, and a known pass/block reason. Facts that
only agree with the check's own external ID do not prove this PR was reviewed.
Skipped checks and infrastructure failures do not prove completion. Setting
`dedupe_same_head: false` permits distinct automatic events to rerun a terminal
head; delivery replays and active runs remain idempotent. Missing evidence or a
dedupe read failure cannot justify a skip. This setting does not change the diff
base or test whether a PR is behind its base.

Event skips create neutral checks with `trigger.skipped` set to
`events_disabled`, `action_not_selected`, or `same_head_reviewed`. Existing rule
skips retain boolean `true`, and draft skips retain the silent no-check behavior.
Mention joins record `in_flight_same_head` in structured logs; rejected mentions
are silent. Run summaries and checks record `trigger.source`, `trigger.actor`
and `trigger.comment_id`. An invalid trigger policy retains the App's existing
review fallback with `trigger.policy_error`. The CLI accepts the document and
continues using its existing rule/draft and `--force-review` behavior.

The event controls use closed enums. `actions` accepts only the four default
actions; `surfaces` accepts only the two default surfaces; `allow` accepts GitHub
associations `OWNER`, `MEMBER`, `COLLABORATOR`, `CONTRIBUTOR`,
`FIRST_TIME_CONTRIBUTOR`, `FIRST_TIMER`, `NONE`, and `MANNEQUIN`. Empty lists select
nothing; `mode: allowlist` with empty `rules` remains invalid, while an empty
`mention.allow` is valid. Bot and App-authored comments are always ignored. Unknown keys and
quoted, numeric, or single-letter boolean values are rejected. Use literal
`true`/`false`. See the [App operator checklist](../cloud/README.md) for the
subscriptions and permission approval needed on existing installations.

Run `uv run rvw policy lint` to validate `.rvw/policies/auto.yaml`, or pass another
policy path; add `--json` for machine-readable diagnostics. When
`pull_request.enabled: true` has `actions: []`, lint emits warning
`empty-pull-request-actions` and exits zero: the valid configuration selects no
automatic reviews. Prefer `enabled: false` when disabling automatic reviews
intentionally. Missing or invalid policy exits 2.

Keep the existing judgment rules in `auto.yaml` and add publication controls:

```yaml
promote_to_blocker:
  agreement_at_least: 2
  severity_at_least: warning
drop:
  agreement_at_most: 1
  severity_at_most: suggestion
block_when:
  severity_at_least: blocker
  confirmed_only: true
publish_state: comment
publish:
  channels: [checks, review]
  checks:
    on_block: failure
    on_pass: success
  inline:
    severity_at_least: suggestion
    max_comments: null
  on_block: comment
  on_pass: comment
  dismiss_on_pass: false
  approve_requires_explicit_opt_in: true
threads:
  resolve_on_fix: true
  reuse_open_thread: true
```

| Setting | Values and behavior |
| --- | --- |
| `publish.channels` | Nonempty list of `checks` and/or `review`; default both. Explicit channels override `publish_state`. Without explicit channels, `publish_state: none` means `[checks]`. |
| `publish.checks.on_block` | `failure` (default) or `neutral`. |
| `publish.checks.on_pass` | `success` (default) or `neutral`. |
| `publish.inline.severity_at_least` | `suggestion` (default), `warning`, or `blocker`. Uses the finding's original severity. |
| `publish.inline.max_comments` | Nonnegative integer or `null` (default, unlimited). Zero makes every finding body-only. |

Checks-only App runs omit `--publish` and create no review, comments or threads.
The check retains the human summary. Review-only App runs suppress detailed check
updates and finish the mandatory bootstrap check as neutral with a localized
“review published without check details” message. Invalid contracts, infrastructure
failures and deadlines always conclude neutral. For advisory checks, set
`publish.checks.on_block: neutral`; this does not change review judgments or CLI exits.

Only confirmed, anchorable new-side findings meeting the floor can become inline
comments. A cap keeps the highest severities first, with finding-key order for
ties. Unlimited default placement keeps its existing order. Findings moved to the
body retain their full explanation, including when synthesis is enabled; posted
inline findings retain a body synopsis. `body_only_count` counts visible findings
without a new inline comment, including those reusing an existing thread.

Inline selection precedes `threads.*` reconciliation. Existing threads matching
current body-only findings are left untouched, and body-only findings create no
threads. Body-only findings still participate in identity matching so a placement
change cannot be mistaken for fix evidence. `reuse_open_thread` and `resolve_on_fix` govern selected inline findings;
historical disappeared findings retain existing fix-proof safeguards. A zero cap
disables living-thread reconciliation entirely. Reused
candidates still occupy their selected place under the cap, so fewer new comments
may be posted. Thread policy does not affect the full body explanation.

Presentation and synthesis settings belong in `.rvw/config.yaml`:

```yaml
locale: ko
voice:
  audience: engineers
  register: formal
  examples:
    - "설정 파일이 없으면 `load_config`는 `ConfigMissing` 오류를 반환합니다."
  allowed_terms: [controller]
synthesis:
  enabled: true
```

`voice.examples` defaults to an empty list and accepts at most three strings, each
at most 200 Unicode characters. Examples follow the generic localized example.
`voice.allowed_terms` defaults to an empty string list and exempts those vocabulary
terms from synthesis prose rejection. Source-domain occurrences of `lane`,
`verdict`, `discovery` and `controller` are also exempt for that review; protected
literals remain exempt. Evidence fidelity and language validation still apply.

`synthesis.enabled: false` skips the synthesis stage, records status `disabled`,
and uses the fallback publication view. It does not change findings, review
judgments or check conclusions. Operator plan, result and thread summaries and
gate errors follow the resolved locale; JSON keys, reason identifiers and exit
codes stay unchanged.

The existing review event controls remain independent of channels. Approval
requires `publish.on_pass: approve` together with
`approve_requires_explicit_opt_in: false`. A bot approval never satisfies code-owner
review, may count toward required approving reviews, and may satisfy last-push
approval; the consuming repository owns that choice.
