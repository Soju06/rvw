## MODIFIED Requirements

### Requirement: Coverage proves lane participation

Every report MUST include a per-lane table of dispatched chunk-expanded runs, valid runs, and findings plus totals, and MUST include kept/excluded diff character accounting and chunk count when a budget report exists.

#### Scenario: One two-chunk lane fails entirely

- **WHEN** an activated lane has three replicas over two chunks and zero valid outputs
- **THEN** the coverage table contains that lane with `6 / 0 / 0` and the budget summary identifies two chunks rather than making the lane indistinguishable from an omitted lane
