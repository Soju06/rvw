## ADDED Requirements

### Requirement: App webhook review eligibility is repository policy

Before enqueueing an eligible `pull_request.opened`, `pull_request.synchronize`, `pull_request.reopened`, or `pull_request.ready_for_review` review, the App MUST read and evaluate `triggers` from `.rvw/policies/auto.yaml` at the captured PR base SHA using webhook/API metadata only. A missing policy MUST select the default empty denylist. An unreadable or invalid policy MUST fall back to the default trigger behavior and record `trigger.policy_error` in the queued review and check facts, never silently skip because of that failure. Invalid policy MUST NOT be partially evaluated.

When `drafts: skip`, a draft MUST still produce no queue message or check run; `ready_for_review` MUST remain eligible. `drafts: review` MUST permit draft reviews. `check_run.rerequested` MUST bypass all trigger matching, enqueue, and record `trigger.bypassed: rerequested`. Existing head-keyed deduplication and synchronize supersession semantics MUST be preserved.

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

### Requirement: A policy skip creates a neutral check without a container

A PR skipped by a repository trigger rule MUST NOT be queued or start a container. The App MUST create or update its check for that head with neutral conclusion, title `<short_name> · Review skipped` (localized through the Worker catalog), and summary `Review skipped by repository policy: <rule name>.` (Korean: `저장소 정책에 따라 검토를 건너뛰었습니다: <rule name>.`). Check facts MUST include `trigger.skipped: true`, the nullable rule name, and policy mode. An allowlist miss MUST use a localized no-matching-rule reason. This path MUST create no review, comments, or threads. The draft default no-check path MUST take precedence over rule skips.

#### Scenario: Release rule skips before enqueue

- **WHEN** a non-draft PR matches the `changesets-release` denylist rule
- **THEN** the App records a neutral localized check naming that rule and creates no review job or container

#### Scenario: Container reports a trigger skip

- **WHEN** an App job receives a valid process PASS with a summary recording a trigger skip and zero VALID lanes
- **THEN** its check remains neutral, preserves trigger facts and localized skip prose, and never reports review success

#### Scenario: Skipped delivery is replayed

- **WHEN** the same skipped head's webhook delivery is replayed and its check already exists
- **THEN** the App updates its own head check instead of enqueueing discovery
