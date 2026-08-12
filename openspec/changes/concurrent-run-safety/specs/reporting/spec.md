## MODIFIED Requirements

### Requirement: Pipeline artifacts are file-first

Every review run MUST create a unique directory under `/tmp/rvw/` by default or the supplied output root and MUST persist target, discovery, merge, optional adjudication, and report artifacts before publication uses them. Ordinary run identifiers MUST carry a sub-second timestamp component, and creation MUST resolve a residual run-directory name collision by regenerating the identifier instead of failing, while remaining safe for run-ID validation and reopening.

#### Scenario: PR review completes

- **WHEN** a PR review reaches REPORT with the default output root
- **THEN** its `/tmp/rvw/<run-id>/` directory contains `target.json`, `discover.json`, `merge.json`, optional `outcome.json`, and `report.md`

#### Scenario: Two runs start on the same target in the same second

- **WHEN** two review runs are created for the same pull request within one second
- **THEN** both receive distinct run directories and neither creation fails
