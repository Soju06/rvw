## MODIFIED Requirements

### Requirement: Lane documents combine frontmatter and prompt text

Each lane document MUST parse YAML frontmatter plus a Markdown prompt body into
a strict lane contract. A lane MAY declare `scope` as `diff`, `direct-deps`, or
`repository`, defaulting to `repository`, and MAY declare `requires_brief`,
defaulting false. Unknown frontmatter remains rejected. The runtime registry
remains external to the package.

#### Scenario: Valid pending lane

- **WHEN** a lane document declares `validation: pending`, a closed rules list,
  and a prompt after the closing `---`
- **THEN** the loader returns a typed lane whose prompt body is the Markdown
  remainder and whose lifecycle is pending

#### Scenario: Malformed frontmatter

- **WHEN** a lane document omits its closing frontmatter delimiter
- **THEN** lane loading fails instead of treating the file as prompt text

#### Scenario: Existing lane omits scope metadata

- **WHEN** a legacy lane document omits `scope` and `requires_brief`
- **THEN** it loads as `repository` scope with no brief requirement

#### Scenario: Lane declares direct dependency scope

- **WHEN** a lane frontmatter sets `scope: direct-deps`
- **THEN** its parsed lane contract exposes that exact scope
