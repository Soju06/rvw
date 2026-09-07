## MODIFIED Requirements

### Requirement: CI composition preserves auto and publication semantics

Automated invocations of the container image and the App MUST call `rvw run` and consume its canonical process and summary artifacts. They MUST preserve the reserved exit categories and COMMENT-only publication behavior, MUST NOT convert BLOCK or failed execution to success, and MUST NOT use stdout prose to determine the result.

#### Scenario: CI auto finds policy blockers

- **WHEN** containerized evaluation returns BLOCK and publishes finding narratives
- **THEN** the invoking automation reports failure from exit 1 and the published review remains a COMMENT

### Requirement: Run verifies supplied target anchors

For each supplied `--base-ref` or `--head-ref`, `run` and its alias MUST compare the resolved target SHA with the supplied SHA before review or publication. Any mismatch MUST return exit 2, status `invalid`, and failure code `target_anchor_mismatch` with expected and observed anchor detail. Without supplied anchors the commands MUST resolve the target through the ordinary resolver. The App MUST supply both captured webhook event anchors.

#### Scenario: PR head advances after the event

- **WHEN** resolved PR head differs from the event head passed through `--head-ref`
- **THEN** review and publication do not start and the process contract records `target_anchor_mismatch`

#### Scenario: PR base advances after the event

- **WHEN** resolved PR base differs from the supplied `--base-ref`
- **THEN** execution fails with the same invalid-input classification even when head is unchanged
