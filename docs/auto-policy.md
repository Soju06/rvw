# Repository publication and synthesis controls

rvw reads `.rvw/policies/auto.yaml` and `.rvw/config.yaml` from the captured base
revision. A pull request cannot change its own review settings through head edits.
Missing keys use the defaults below. Malformed presentation settings fail with
`presentation_config_invalid`; malformed publication settings fail with
`publish_policy_invalid`.

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
