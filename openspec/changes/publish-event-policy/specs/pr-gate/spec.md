## MODIFIED Requirements

### Requirement: Gate publication uses localized human findings

Gate publication MUST derive its body from the persisted verdict and presentation snapshot through the human publication view and locale catalogs. It MUST retain PASS/BLOCK, the actionable finding list, and human disposition reasons, and MUST omit run IDs, actor identity, and inheritance internals from publication prose. Structured gate verdict artifacts MUST retain those diagnostic facts. Publication MUST satisfy the shared language gate without changing disposition or anchor semantics. The review event MUST follow the same repository `publish` policy as `run`: the gate verdict selects `on_block` or `on_pass`, and every clamp, same-head idempotency rule, dismissal rule, and thread reconciliation rule defined by the reporting capability applies unchanged. In target mode the gate MUST resolve the policy inside its provisioned checkout at the captured base before any lane is dispatched, MUST exit 2 on a policy fault without reviewing, MUST persist the policy as `policy.json`, and MUST publish its own dry-run or execute with that verified policy; resume and publication-only republish MUST re-read the base ref when it is reachable and otherwise clamp to COMMENT. A fault in the policy's `publish` or `threads` block MUST be recorded in `publish-status.json` as a failed attempt naming `publish_policy_invalid` and MUST exit 2 without publishing.

#### Scenario: Accepted blocker is published

- **WHEN** a completed gate verdict with an accepted blocker is published under the default policy
- **THEN** the review body shows the finding, its localized disposition, and the human reason, and the event is COMMENT

#### Scenario: Blocking verdict under a request-changes policy

- **WHEN** the base policy sets `publish.on_block: request_changes` and the gate verdict is BLOCK
- **THEN** `--execute` posts a REQUEST_CHANGES review pinned to the gate head and `publish-status.json` records `event: REQUEST_CHANGES`

#### Scenario: Policy block is malformed

- **WHEN** the base policy's `publish` block is invalid at publication time
- **THEN** gate appends `ok: false` with `publish_policy_invalid` and exits 2 without a GitHub write

### Requirement: Publication attempts persist status independently

Every gate publication attempt MUST append one record to the JSON array in `publish-status.json` on success and failure. A legacy single-object artifact MUST load as the first array record. Gate MUST read and write the artifact relative to the pinned run-directory descriptor and MUST open the write target with `O_NOFOLLOW | O_CREAT | O_TRUNC`, rejecting a symlinked existing file. Each record MUST contain `attempted_at`, mode `dry_run` or `execute`, boolean `ok`, a bounded secret-redacted failure `detail` or null on success, and boolean `republish`; successful records MUST also contain the `inline_count` and `body_fallback_count` returned by publication, the `event` actually used (`COMMENT`, `REQUEST_CHANGES`, `APPROVE`, or null when no review was posted), and `skipped` (null, `duplicate_review_same_head`, `on_pass_none`, or `head_moved`). Publication status MUST remain separate from the immutable completed `GateVerdict` evidence.

#### Scenario: Publication fails

- **WHEN** GitHub rejects an execute-mode publication
- **THEN** gate persists `ok: false` with the attempt mode, republish state, timestamp, and redacted detail before exiting

#### Scenario: Dry-run publication succeeds

- **WHEN** a dry-run publication of a completed verdict succeeds
- **THEN** gate appends `ok: true`, mode `dry_run`, null detail, the applicable republish state, the inline and body-fallback counts, the selected event, and a null skip reason without discarding prior attempts

#### Scenario: Same-head duplicate

- **WHEN** rvw already posted a REQUEST_CHANGES for the gate head
- **THEN** the record carries `ok: true`, `event: null`, and `skipped: duplicate_review_same_head`
