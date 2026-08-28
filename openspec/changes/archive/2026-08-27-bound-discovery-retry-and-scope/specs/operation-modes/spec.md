## MODIFIED Requirements

### Requirement: High-cost discovery requires explicit non-interactive acknowledgement

Every command that can start DISCOVER (`review`, `auto`, gate target mode, and
`stack review`) MUST calculate its discovery preflight before starting runtime
work. The preflight MUST report initial run count, one-retry upper-bound run
count, exact aggregate initial prompt characters, configured run ceiling, and
runtime model/reasoning effort. The default ceiling MUST be 12 positive runs;
commands MAY accept a positive `--max-discovery-runs` override. Discovery MUST
fail closed unless `--allow-heavy-discovery` is supplied when discovery replicas
are at least two, when the one-retry upper bound exceeds the configured ceiling,
or when the selected reasoning effort is `max`. `plan` MUST report the same
preflight but MUST not require the acknowledgement because it starts no runtime
work. The acknowledgement MUST not depend on interactive confirmation or TTY
state. The preflight MUST identify skipped brief-required lanes as zero runtime
work, while retaining their explicit skip reason in plan details.

#### Scenario: Default max-effort review is not acknowledged

- **WHEN** `rvw review` uses the default `max` reasoning policy without `--allow-heavy-discovery`
- **THEN** it exits before starting DISCOVER and identifies the required flag

#### Scenario: Replica retry shape exceeds the ceiling

- **WHEN** a review plans twelve initial discovery runs under a ceiling of 12
- **THEN** its retry upper bound of 24 requires `--allow-heavy-discovery` before any runtime work starts

#### Scenario: Informative plan has high-cost conditions

- **WHEN** `rvw plan` renders a preflight whose policy uses `max` effort
- **THEN** it reports the acknowledgement reasons and exits successfully
