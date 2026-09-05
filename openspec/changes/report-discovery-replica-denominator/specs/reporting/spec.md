## ADDED Requirements

### Requirement: Finding agreement discloses discovery coverage

Every machine-rendered finding agreement MUST use the distinct discovery replica count as its numerator and the run's configured discovery replica count as its denominator. Ordinary report items, pattern-fold items, inline publication comments, retained body items, and HTTP 422 fallback items MUST use the same denominator and MUST NOT derive it from adjudication votes. Runs whose persisted discovery artifacts predate denominator derivation support MAY retain the historical denominator when exact discovery coverage is unavailable.

#### Scenario: Single-replica report is rendered

- **WHEN** a run configured with one discovery replica renders an ordinary finding with agreement one
- **THEN** the report states `복제 동의 1/1` regardless of the number of adjudication votes

#### Scenario: Two-replica pattern is rendered

- **WHEN** a run configured with two discovery replicas renders a pattern-fold item whose highest-priority member has agreement one
- **THEN** the pattern item states `복제 동의 1/2`

#### Scenario: Publication rerenders a finding item

- **WHEN** publication builds an inline comment or HTTP 422 body fallback from a run configured with one discovery replica
- **THEN** every rerendered finding item states `/1` and no rerendered item states `/3`
