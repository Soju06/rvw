## MODIFIED Requirements

### Requirement: Sampling compares enum and free variants

The sampling gate MUST pass its fixture diff through the shared exclusion and chunk planner, MUST execute closed-enum and free-rule-ID variants with equal replica counts for every chunk in one bounded wave, MUST report sorted free-variant rule IDs absent from the lane's closed enum as `novel_rule_ids`, and MUST report in-enum enum-only and free-only `(file, line)` sites separately as site variance. It MUST retain the `PASS` and `REVIEW` verdict values, MUST report `REVIEW` and exit 1 only when `novel_rule_ids` is nonempty, and MUST otherwise report `PASS` and exit 0 even when site variance exists.

#### Scenario: Free variant invents a rule ID

- **WHEN** any valid free-variant replica on any fixture chunk emits a rule ID outside the lane's generated closed enum
- **THEN** sampling lists that ID in `novel_rule_ids`, reports `REVIEW`, and exits 1

#### Scenario: Replicas find an existing rule at different sites

- **WHEN** free-only or enum-only sites use rule IDs contained in the lane's closed enum and no novel rule ID is emitted
- **THEN** sampling records those sites as variance, reports `PASS`, and exits 0

#### Scenario: Novel rule appears at an enum-covered site

- **WHEN** the free variant emits an out-of-enum rule ID at a `(file, line)` also found by the enum variant
- **THEN** sampling still reports that rule ID as novel because gap detection is independent of site-set difference

#### Scenario: Large fixture uses production chunk semantics

- **WHEN** a sampling fixture exceeds the per-prompt aggregate character budget after exclusions
- **THEN** both variants execute every replica on every planner-produced chunk while one-chunk fixture artifact paths remain unchanged
