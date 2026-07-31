## MODIFIED Requirements

### Requirement: Stack publication is body-only and dry-run by default

The `stack publish` command MUST write `publish-payload.json` containing a
body-only COMMENT review and the captured tip head SHA as `commit_id`, without a
network call unless `--execute` is supplied. Execute mode MUST make at most one
publication call after successful full-stack anchor revalidation and MUST send
the same commit-pinned payload persisted for inspection.

#### Scenario: Operator inspects a stack payload

- **WHEN** `rvw stack publish --run <id>` is invoked without `--execute`
- **THEN** the saved payload contains `event: COMMENT`, `commit_id` equal to the
  manifest tip head, and the stack report body, contains no inline comments, and
  no GitHub review is created
