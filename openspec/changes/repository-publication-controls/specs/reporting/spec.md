## MODIFIED Requirements

### Requirement: Confirmed anchors become inline comments

Confirmed groups that have a new-side line and `anchorable: true` MUST be emitted as right-side inline comments subject to repository inline policy. Every non-rejected finding MUST also remain in its body section, including findings posted inline. With synthesis, posted-inline findings MUST have a short body entry containing title, source location and consequence while inline items retain the full explanation. Without synthesis the body MUST retain the existing full finding shape. An empty-section message MUST appear only when that section contains zero findings.

The default inline severity floor MUST be suggestion and the default comment cap MUST be null (unlimited). A warning or blocker floor MUST leave lower-severity findings body-only in full. A nonnegative integer cap MUST select highest-severity candidates first, breaking ties by stable finding identity. Living-thread reconciliation MUST use only inline candidates; body-only findings MUST NOT create or maintain threads. Existing `threads.*` controls MUST apply within those candidates. A zero inline cap MUST disable living-thread reconciliation.

#### Scenario: Finding is outside the diff

- **WHEN** a confirmed finding has `anchorable: false`
- **THEN** it remains in the body and is not sent as an inline comment

#### Scenario: Required changes have inline threads

- **WHEN** the summary counts two confirmed blockers posted inline
- **THEN** the body lists both blockers under required changes and does not show an empty-section message there

#### Scenario: Severity and count restrict inline placement

- **WHEN** a repository selects warning and a cap of one for a blocker, warning and suggestion
- **THEN** only the blocker is selected inline, both other findings render in full in the body and their matching existing threads are left untouched

## ADDED Requirements

### Requirement: Publication controls are persisted as facts

Summary publish facts MUST include resolved channels and inline_policy containing severity_at_least, max_comments and body_only_count. Missing legacy fields MUST load with defaults. An absent review channel MUST prevent all review, comment and thread writes, even with an explicit publication request. Non-inline findings MUST render in full in the review body.

#### Scenario: Suggestions stay body-only

- **WHEN** the repository sets the warning floor and review includes one confirmed suggestion and one anchorable warning
- **THEN** only the warning is an inline candidate, the suggestion remains fully explained in the body, and body_only_count includes the suggestion
