## Why

Repositories need to control when the App incurs a full review fan-out. Consumer PR 2026-09-11 exposed an unchanged-head Ready event while behind base; automatic admission should recognize completed work for that PR, while explicit human mentions should allow a rerun.

## What Changes

- Add strict automatic action selection, mention controls, and same-PR/head dedupe to the base-ref auto policy, with exact shared parser expectations and a warning for enabled automatic events with no selected actions.
- Admit authorized human mentions on both PR comment surfaces, exclude blockquote/code/HTML mentions and team-mention suffixes, preserve token boundaries across Markdown formatting, refresh expired App identity before rejecting a new slug, and acknowledge accepted or joined requests with eyes reactions.
- Reuse the existing PR/head executor for completed-review evidence, serialized starts, and delivery/comment replay protection; retain a first-write-wins comment pin across pushes. Require requested-job identity for check fallback; commit association alone never suppresses review.
- Preserve legacy trigger facts while adding source, actor, comment identity, and closed machine-readable skip reasons.
- Update App manifest defaults and operator documentation. Repository-wide scheduling is outside this change.

## Capabilities

### Modified Capabilities

- `operation-modes`: additive trigger event/schema controls, summary facts, and policy lint warning.
- `cloud-app-platform`: webhook admission, PR-scoped completed-head dedupe, mention reruns, executor idempotency, and App subscriptions/permissions.

## Impact

Python policy and summary models, Worker policy readers, webhook and existing PR/head executor, GitHub helpers, packaged policy, and App manifest. Separate trigger/publication base-ref fetches and their size limits remain intact. Wrangler bindings, migrations, queues, and executor alarm roles remain at the baseline. No CLI mention command, external registry changes, deployment, or publication.
