## MODIFIED Requirements

### Requirement: Routine review modes default to one replica

The `rvw review` and `rvw auto` commands MUST default to one discovery replica
and three adjudication replicas. `plan`, `review`, `auto`, `gate`, and `stack
review` MUST expose `--discovery-replicas` as the positive discovery replica
count and MUST preserve an independently positive `--adjudicate-replicas`
count. `--replicas` MUST remain a compatibility alias for the discovery count
and MUST emit a deprecation warning; an invocation that supplies both spellings
MUST fail before execution. `rvw plan` MUST report the discovery count as
`replicas`, MUST report the adjudication count as `adjudicate_replicas`, and
MUST calculate discovery run totals from the discovery count only.

#### Scenario: Review uses split defaults

- **WHEN** `rvw review` is invoked without replica overrides
- **THEN** the shared pipeline receives one discovery replica and three
  adjudication replicas

#### Scenario: Plan reports split routine defaults

- **WHEN** `rvw plan` renders a plan without replica overrides
- **THEN** its payload reports `replicas: 1` and `adjudicate_replicas: 3`, and
  its total discovery run count uses one run per active lane per diff chunk

#### Scenario: Discovery replication is explicitly requested

- **WHEN** a review command is invoked with `--discovery-replicas 2`
- **THEN** the shared pipeline receives two discovery replicas and the
  independently selected adjudication count

#### Scenario: Single-vote adjudication is explicitly requested

- **WHEN** a review command is invoked with `--adjudicate-replicas 1`
- **THEN** the shared pipeline preserves one adjudication replica without
  changing discovery dispatch, retry, widening, or voting rules

#### Scenario: Legacy replica option is used

- **WHEN** a review command is invoked with `--replicas 2`
- **THEN** it preserves two discovery replicas and emits a deprecation warning
  directing the operator to `--discovery-replicas`

#### Scenario: Replica spellings conflict

- **WHEN** a command supplies both `--discovery-replicas` and `--replicas`
- **THEN** it fails before any pipeline or runtime work starts

#### Scenario: Replica count is invalid

- **WHEN** either replica option is supplied with a value below one
- **THEN** the command rejects the invocation before executing the pipeline

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
state. Each runtime execution MUST persist its acknowledged preflight as
`preflight.json` before runtime dispatch, and every structured result payload
for that execution MUST include the same preflight values. `stack review` MUST
aggregate all member preflights and require acknowledgement before it starts
the first member's DISCOVER dispatch.

#### Scenario: Default max-effort review is not acknowledged

- **WHEN** `rvw review` uses the default `max` reasoning policy without
  `--allow-heavy-discovery`
- **THEN** it exits before starting DISCOVER and identifies the required flag

#### Scenario: Replica retry shape exceeds the ceiling

- **WHEN** a review plans twelve initial discovery runs under a ceiling of 12
- **THEN** its retry upper bound of 24 requires `--allow-heavy-discovery`
  before any runtime work starts

#### Scenario: Informative plan has high-cost conditions

- **WHEN** `rvw plan` renders a preflight whose policy uses `max` effort
- **THEN** it reports the acknowledgement reasons and exits successfully

#### Scenario: Acknowledged discovery records its preflight

- **WHEN** an acknowledged discovery command starts
- **THEN** its run artifact contains `preflight.json` before runtime dispatch
  and its structured result payload includes the same preflight values

#### Scenario: Stack discovery is acknowledged before any member dispatch

- **WHEN** `stack review` plans more than one member
- **THEN** it aggregates every member's initial runs, retry bound, and prompt
  characters, persists that stack preflight, and requires acknowledgement
  before dispatching the first member
