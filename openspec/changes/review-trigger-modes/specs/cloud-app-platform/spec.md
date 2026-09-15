## ADDED Requirements

### Requirement: Human comment mentions request PR reviews

The App MUST admit only `issue_comment.created` with a PR-linked issue and `pull_request_review_comment.created`; other actions and non-PR issues MUST return 204 before any App API call. Bodies without `@` MUST return 204 before App identity lookup or Markdown parsing regardless of cache state. Authenticated App identity MUST be cached in module scope across requests for five minutes. With an unexpired cached slug, a cheap case-insensitive literal `@<slug>` substring precheck MUST precede any App API call or Markdown parse. An expired cached identity MUST NOT reject a candidate before authenticated identity refresh. An eligible cold isolate or expired cache MAY make one authenticated `GET /app` to learn the current slug and MUST apply that precheck before parsing or further API work. Identity lookup failure MUST return 204 with a structured log and MUST NOT return 400.

The App MUST reuse one Markdown parser per isolate and match case-insensitive whole `@<slug>` tokens, optionally followed by review, from adjacent visible text across formatting and link-label tokens within the same inline block. It MUST exclude inline/fenced/indented code, inline/block HTML, and every blockquote. It MUST reject longer usernames and email-like tokens even when formatting splits them. A slash immediately after the slug MUST reject the match as team-mention syntax; period, comma, question mark, exclamation mark, apostrophe, and colon suffixes MUST remain accepted. It MUST reject Bot commenters and its own authenticated App identity regardless of the association allowlist. App metadata MUST match the configured numeric App ID.

The App MUST obtain the base review installation token, resolve the current PR, require it to be open, and evaluate `events.mention.enabled`, `surfaces`, and `allow` from its captured base-ref policy. Authorized mentions MUST bypass draft/rule filters and completed-head dedupe. Rejected mentions MUST be silent except for structured logs and MUST create no job, check, review, or comment. Accepted mentions MUST use the ordinary review job and top-level trigger provenance. A mention while the same PR/head executor is nonterminal MUST join with `trigger.skipped: in_flight_same_head` through the executor's real serialized start/identity path and MUST NOT start a second sandbox. A webhook join hint MUST still reach the queued executor start path so the joined identity is consumed durably and cannot become a rerun if execution completes before delivery. Accepted and joined mentions MUST receive eyes reactions when permitted. Reactions MUST be fail-soft; optional Issues write token scope MUST be requested only after the normal review token and MUST fall back to base permissions on 403/422.

The comment-scoped `mention:i:r:<surface>:<commentId>` pin MUST preserve the first validated job message transactionally and MUST have no alarm. Executor delivery/comment identities MUST prevent replay of an accepted or joined comment from starting another execution, including after completion or a push. A genuinely new comment MUST remain eligible to target the new head.

#### Scenario: Human asks for a draft review

- **WHEN** an allowed human mentions the App outside excluded content on an open draft whose trigger rules would skip
- **THEN** the App enqueues the ordinary review job, records mention provenance, and reacts eyes

#### Scenario: Formatting does not create mention boundaries

- **WHEN** the body is foo**@slug** or @slug**bot**
- **THEN** no mention matches because adjacent visible text remains one longer token

#### Scenario: Visible whole mentions survive formatting

- **WHEN** the body contains **@slug**, (@slug), @slug comma, @SLUG, or a link with label @slug
- **THEN** its whole mention matches independently of formatting and case

#### Scenario: Team mention does not request App review

- **WHEN** the only candidate is `@slug/review` or another slash suffix after the App slug
- **THEN** the webhook returns 204 and queues no review

#### Scenario: Sentence punctuation preserves a mention

- **WHEN** a whole mention is followed by `.`, `,`, `?`, `!`, `'s`, or `:`
- **THEN** the mention remains eligible

#### Scenario: Reply quote does not request review

- **WHEN** the only mention is inside a blockquote
- **THEN** no review is requested

#### Scenario: Fresh mention follows a quoted request

- **WHEN** a quoted mention is followed by a fresh unquoted whole mention
- **THEN** the unquoted mention remains eligible

#### Scenario: Ordinary discussion avoids identity and parsing costs

- **WHEN** a created PR comment contains no at-sign with a cold, fresh, or expired identity cache
- **THEN** the webhook returns 204 with zero App API calls and zero Markdown parses

#### Scenario: Cached slug rejects unrelated mentions cheaply

- **WHEN** a created comment does not contain the unexpired cached App slug as a literal case-insensitive mention substring
- **THEN** the webhook returns 204 without an App API call or Markdown parse

#### Scenario: Expired identity refreshes for a renamed App

- **WHEN** a created comment mentions the App's new slug after its old cached identity has expired
- **THEN** the webhook refreshes authenticated identity with one GET /app and admits the otherwise eligible mention using the new slug

#### Scenario: App identity is unavailable

- **WHEN** an otherwise eligible cold-isolate comment cannot resolve authenticated App identity
- **THEN** the webhook logs the failure and returns 204 without a review

#### Scenario: Rejected mentions stay silent

- **WHEN** a mention is excluded content, a longer token, from a Bot or disallowed association, authored by the App itself, for a closed PR, or disabled by policy
- **THEN** no job, review, check, or comment is created

#### Scenario: Reaction permission is unavailable

- **WHEN** optional Issues write is refused with 403 or 422 or the reaction endpoint rejects an accepted mention
- **THEN** base review permissions remain usable and reaction failure does not cancel the review

#### Scenario: Mention reruns a completed PR head

- **WHEN** a distinct allowed comment mentions an exact head previously completed for this PR
- **THEN** a new run starts with the new comment provenance after any old cleanup/check obligations settle

#### Scenario: In-flight mention joins this PR only

- **WHEN** a mention targets this PR/head executor while queued, provisioning, running, or publishing
- **THEN** no second sandbox starts, structured facts record in_flight_same_head, and the comment receives eyes

#### Scenario: Old mention is replayed after completion or push

- **WHEN** an accepted or joined comment is redelivered after completion, a later rerun, or a PR push
- **THEN** its first pinned anchors and handled identity prevent a new execution

#### Scenario: New comment after a push requests the new head

- **WHEN** an allowed human submits a new comment after the PR head changes
- **THEN** the new comment has its own pin and may request review of the new head

## MODIFIED Requirements

### Requirement: GitHub App contract is declared
The manifest MUST declare app name `rvw`, permissions `checks:write`, `pull_requests:write`, `contents:read`, `metadata:read`, events `pull_request`, `check_run`, and `check_suite` (installation events are delivered to every App implicitly and MUST NOT be listed in `default_events`), and replaceable placeholders for the deployer's fork URL and Worker-host webhook and callback URLs.

The manifest MUST additionally declare `issues:write` and events `issue_comment` and `pull_request_review_comment`.

#### Scenario: Manifest template is used for registration
- **WHEN** a deployer follows the documented manifest registration flow
- **THEN** the deployer replaces the fork and Worker-host placeholders before GitHub presents exactly the declared permissions and events



### Requirement: App webhook review eligibility is repository policy

Before enqueueing an eligible `pull_request.opened`, `pull_request.synchronize`, `pull_request.reopened`, or `pull_request.ready_for_review` review, the App MUST read and evaluate `triggers` from `.rvw/policies/auto.yaml` at the captured PR base SHA using webhook/API metadata only. A missing policy MUST select the default empty denylist. An unreadable or invalid policy MUST fall back to the default trigger behavior and record `trigger.policy_error` in the queued review and check facts, never silently skip because of that failure. Invalid policy MUST NOT be partially evaluated.

When `drafts: skip`, a draft MUST still produce no queue message or check run; `ready_for_review` MUST remain eligible. `drafts: review` MUST permit draft reviews. `check_run.rerequested` MUST bypass all trigger matching, enqueue, and record `trigger.bypassed: rerequested`. Existing head-keyed deduplication and synchronize supersession semantics MUST be preserved.

Automatic eligibility MUST additionally honor strict `events.pull_request.enabled`, selected `actions`, and `dedupe_same_head` after existing draft/rule evaluation. Disabled events MUST use `trigger.skipped: events_disabled`; unselected actions MUST use `action_not_selected`. Ready MUST normalize stale draft metadata to ready, then honor these additional filters. A policy-read/parse failure MUST bypass the additional filters and retain the existing review fallback. Synchronize supersession MUST still occur on policy skips.

With `dedupe_same_head: true`, the App MUST skip before queue insertion with `same_head_reviewed` only when completed-review evidence exists for the same installation, repository, PR number, and exact head. It MUST use only the existing PR/head executor record `i:r:p:h` and, when that evidence is absent or inconclusive, paginated own-App check runs on the commit using the installation token. A review of the same SHA for another PR MUST NOT suppress this PR. API failure or missing/inaccessible history MUST be logged and MUST NOT itself suppress admission.

A durable `reviewCompleted: true` marker MUST remain completion evidence across later reruns; new completion MUST require terminal completed mapping, a defined pass/block outcome, a parseable summary, positive valid lanes, and no trigger skip. A legacy record lacking that marker MUST count only when its state is completed, its conclusion is success or failure, and its trigger is not skipped. A neutral legacy record or infrastructure-failed state MUST NOT establish completion. Check evidence MUST require numeric App-ID equality, exact head, completed status, a string external ID excluding `:trigger-skip`, and no truthy trigger skip. Recoverable job identity MUST be authoritative: a parseable `external_id` in `installation:repo:pr:sha` form and any job identity recovered from structured `job_id` or `artifact_key` facts MUST match the requested job's installation, repository, PR, and head. A contradictory recovered identity MUST reject the check regardless of `pull_requests[]` associations. At least one such identity MUST be recoverable; commit association alone, including `pull_requests[].number`, MUST NOT establish PR evidence or suppress admission. New structured output MUST establish completion through `review_completed: true`; explicit false MUST reject. Legacy check output without that marker MUST additionally have job/artifact facts matching the requested job identity, positive valid lanes, and a known English/Korean pass/block reason suffix. Internal consistency with the check's own external ID alone MUST NOT establish legacy PR evidence. Check conclusion alone MUST NOT establish completion.

The existing executor's serialized `start()` and durable delivery/comment identity checks MUST provide same-PR/head idempotency. Distinct automatic deliveries with dedupe disabled MUST be permitted to restart terminal work; mentions and check rerequests MUST retain explicit-rerun behavior. Pending cleanup/check-update obligations and their sandbox/process/check identifiers MUST be preserved and settled before replacing a terminal executor record. This change MUST NOT introduce another scheduling object, queue outbox, or alarm role; the baseline executor lifecycle alarm roles MUST be retained.

#### Scenario: Draft defaults are unchanged

- **WHEN** a draft opened event uses an absent trigger block
- **THEN** the App creates neither a check run nor a queued job

#### Scenario: Repository reviews drafts

- **WHEN** a draft opened event uses `drafts: review` and no matching denylist rule
- **THEN** the App enqueues the review

#### Scenario: Policy cannot be read

- **WHEN** reading the captured base-ref policy fails for a non-draft PR
- **THEN** the App enqueues review with default triggers and `trigger.policy_error`

#### Scenario: Human rerequests a skipped release

- **WHEN** a human rerequests the check for a PR matching a repository denylist rule
- **THEN** the App enqueues without applying the filter and preserves `trigger.bypassed: rerequested`

#### Scenario: Event controls skip before queue insertion

- **WHEN** an otherwise eligible automatic action is disabled or unselected by valid policy
- **THEN** the App records the corresponding closed skip reason and queues no job

#### Scenario: Completed PR head is deduplicated on Ready

- **WHEN** a Ready event retains the exact head already reviewed for this PR and dedupe is enabled
- **THEN** the App records same_head_reviewed before queue insertion even when draft metadata is stale

#### Scenario: Another PR has the same completed SHA

- **WHEN** a completed own-App check has `review_completed: true` and another PR's external job identity while pull_requests lists both PRs
- **THEN** that check does not suppress this PR even though its head SHA and commit association match

#### Scenario: Legacy facts identify another PR

- **WHEN** a completed own-App check has legacy lane/reason output and job_id or artifact_key facts for another PR, even if internally consistent with its external ID and pull_requests lists this PR
- **THEN** those facts do not establish completion for the requested PR and admission is not suppressed

#### Scenario: Commit association has no job identity

- **WHEN** a completed own-App check lists this PR in pull_requests but no job identity is recoverable from its external ID or structured facts
- **THEN** the ambiguous association does not suppress review of this PR

#### Scenario: Commit check identifies this PR

- **WHEN** local completion is missing and a completed own-App check has valid completion evidence plus a recoverable job identity matching the requested installation, repository, PR, and head with no contradictory identity
- **THEN** the App suppresses an automatic duplicate for this PR and exact head

#### Scenario: Completion lookup fails open

- **WHEN** the check API fails or accessible history contains no qualifying review for this PR
- **THEN** completed-head lookup does not suppress admission

#### Scenario: Terminal cleanup is still pending

- **WHEN** a new rerun reaches the real executor start path after reinstantiation with pending cleanup or terminal check update
- **THEN** the old sandbox/process/check identifiers and obligations remain available and no replacement execution starts until they settle

### Requirement: A policy skip creates a neutral check without a container

A PR skipped by a repository trigger rule MUST NOT be queued or start a container. The App MUST create or update its check for that head with neutral conclusion, title `<short_name> · Review skipped` (localized through the Worker catalog), and summary `Review skipped by repository policy: <rule name>.` (Korean: `저장소 정책에 따라 검토를 건너뛰었습니다: <rule name>.`). Check facts MUST include `trigger.skipped: true`, the nullable rule name, and policy mode. An allowlist miss MUST use a localized no-matching-rule reason. This path MUST create no review, comments, or threads. The draft default no-check path MUST take precedence over rule skips.

Event-selection and completed-head skips MUST also produce neutral localized checks without queueing or starting a container. For these skips, check facts MUST use their closed string reason in `trigger.skipped`, nullable rule, and policy mode; rule skips MUST retain the boolean fact above. Skip checks MUST use a separate stable external identity so later skips do not overwrite active checks or completed-review evidence.

#### Scenario: Release rule skips before enqueue

- **WHEN** a non-draft PR matches the `changesets-release` denylist rule
- **THEN** the App records a neutral localized check naming that rule and creates no review job or container

#### Scenario: Container reports a trigger skip

- **WHEN** an App job receives a valid process PASS with a summary recording a trigger skip and zero VALID lanes
- **THEN** its check remains neutral, preserves trigger facts and localized skip prose, and never reports review success

#### Scenario: Skipped delivery is replayed

- **WHEN** the same skipped head's webhook delivery is replayed and its check already exists
- **THEN** the App updates its own head check instead of enqueueing discovery
