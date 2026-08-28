## MODIFIED Requirements

### Requirement: Invalid replicas use one all-lane retry

An invalid replica MUST be excluded from finding enrichment. A lane/chunk group
MUST receive exactly one replacement wave only when every initial replica is
INVALID and every invalid reason is `json_parse_error` or
`schema_validation_error`; an initial wave MUST NOT contain retry feedback. A
timeout, cancellation, budget, spawn, completion-marker, missing-artifact, or
other invalid reason MUST NOT cause an identical full-wave retry. Any lane/chunk
group with no valid result after its permitted retry decision MUST make
DISCOVER fail closed as incomplete rather than contributing a zero-finding PASS.
Replacement artifacts and ordered attempt coverage retain the existing contract,
and legacy discovery artifacts continue to load with empty attempt history.

#### Scenario: One of three replicas is invalid

- **WHEN** two replicas for one lane-chunk are VALID and one is INVALID
- **THEN** discovery keeps the two valid outputs and does not retry that lane-chunk

#### Scenario: All replicas have schema failures

- **WHEN** every initial replica for one lane/chunk has `schema_validation_error`
- **THEN** it receives one replacement wave with those reasons in feedback

#### Scenario: All replicas are invalid

- **WHEN** all three initial replicas for one lane-chunk are INVALID with
  correctable schema or format reasons
- **THEN** the dispatcher executes one replacement wave for that lane-chunk and
  performs no further retry

#### Scenario: All replicas time out

- **WHEN** every initial replica for one lane/chunk has `exit_nonzero:124`
- **THEN** no replacement wave starts and DISCOVER fails closed as incomplete

#### Scenario: Replacement prompt names prior failures

- **WHEN** every initial replica of one lane-chunk is INVALID with machine-readable reasons
- **THEN** that lane-chunk's replacement prompt lists each prior replica's invalid reason while another lane's unretried prompt contains none

#### Scenario: Retry preserves initial artifacts

- **WHEN** a lane-chunk's replacement wave completes after an all-INVALID initial wave
- **THEN** the initial wave's prompt, log, and output artifacts are unchanged and the replacement artifacts exist in a separate directory

#### Scenario: Retried coverage keeps the initial failure reason

- **WHEN** a lane-chunk retried after an initial `exit_nonzero` failure succeeds in the replacement wave
- **THEN** its persisted coverage row is valid, and its attempt records list the initial INVALID attempt with reason `exit_nonzero` followed by the valid retry attempt

#### Scenario: Legacy discovery artifact loads

- **WHEN** a `discover.json` persisted before attempt records is loaded
- **THEN** loading succeeds and each coverage run reports empty attempt history

#### Scenario: Exact-match resume reuses a valid result

- **WHEN** an interrupted run's target, prompt, lane document, schema, policy, and RVW version match a rebuilt discovery plan
- **THEN** resume reuses its VALID result and dispatches only identities without one

### Requirement: Dynamic brief falls back to PR claims

Dynamic lanes MUST use an operator-supplied brief when present, SHALL otherwise
use the PR title and body when available, and MUST label the PR-derived brief
as an UNVERIFIED claim of intent. A dynamic lane declaring `requires_brief:
true` with neither source MUST not invoke a runtime and MUST record zero
dispatch with `skipped_reason: brief_unavailable`.

#### Scenario: No operator brief for a PR

- **WHEN** a PR target has a title and body but no `--dynamic-brief`
- **THEN** dynamic prompts contain the title/body and the UNVERIFIED note

#### Scenario: No brief source exists for a required lane

- **WHEN** a commit target has no operator brief and an activated dynamic lane declares `requires_brief: true`
- **THEN** that lane is recorded as skipped for `brief_unavailable` and makes no model call

#### Scenario: No brief source exists

- **WHEN** a commit target has no operator brief and a dynamic lane does not
  require one
- **THEN** its prompt states that the brief is unavailable and findings should
  be marked inconclusive
