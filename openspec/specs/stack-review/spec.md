# stack-review Specification

## Purpose

Define explicit stacked pull-request resolution, immutable member review,
cross-head finding lineage adjudication, and tip-only COMMENT publication.

## Requirements
### Requirement: Stack input is explicit and ordered

The stack commands MUST accept a comma-separated list containing at least two
unique positive pull-request numbers, MUST preserve caller order, and MUST NOT
infer, reorder, or extend the stack.

#### Scenario: Caller supplies a three-member stack

- **WHEN** `--prs 11,12,14` is supplied
- **THEN** planning resolves exactly pull requests 11, 12, and 14 in that order

#### Scenario: Caller repeats a pull request

- **WHEN** `--prs 11,12,11` is supplied
- **THEN** validation fails before any member review runs

### Requirement: Planning proves one direct open chain

Planning MUST resolve every member to the same repository, MUST require every
member to be open and unmerged, and MUST require each child's base ref and SHA
to equal its direct parent's head ref and SHA.

#### Scenario: Child is based on the parent head

- **WHEN** pull request 12 has base ref/SHA equal to pull request 11's head
  ref/SHA
- **THEN** their adjacent edge is valid

#### Scenario: Stack skips an intermediate base

- **WHEN** a child's base SHA differs from the listed parent's head SHA
- **THEN** planning fails with the affected parent and child numbers

#### Scenario: Members come from different repositories

- **WHEN** one resolved pull request has a different repository identity
- **THEN** planning fails before writing a valid stack manifest

### Requirement: Stack manifests pin every member

A stack manifest MUST record a schema version, unique safe stack run ID,
repository identity, ordered pull-request metadata, and each member's immutable
base/head refs and SHAs. A completed plan MUST be reloadable without querying
GitHub again.

#### Scenario: Plan succeeds

- **WHEN** every member and edge is valid
- **THEN** `stack-manifest.json` contains the ordered captured anchors and the
  CLI returns its stack run ID and artifact path

### Requirement: Review fails closed on moved anchors

Stack review MUST validate the full chain before member work, MUST provision
each member at its captured detached head with a clean checkout, and MUST
revalidate all members and edges after model work. Any changed state, ref, SHA,
repository identity, or edge MUST fail the run without producing a completed
stack report.

#### Scenario: Earlier PR moves during review

- **WHEN** an earlier member's head SHA differs during final revalidation
- **THEN** stack review records the stale member and fails without declaring
  the stack complete

### Requirement: Every member uses the ordinary review pipeline

Stack review MUST execute the common DISCOVER, MERGE, ADJUDICATE, and REPORT
pipeline exactly once for every member in caller order and MUST persist each
ordinary run ID after that member completes.

#### Scenario: Third member review fails operationally

- **WHEN** the first two ordinary reviews complete and the third fails
- **THEN** `member-runs.json` retains the first two run references and no
  completed stack report is emitted

### Requirement: Earlier claims are rechecked at every descendant

After reviewing a descendant member, stack review MUST batch all actionable
lineages originating in earlier members into one presence adjudication pass per
replica against that descendant checkout. It MUST add actionable findings
originating in the current member only after rechecking older lineages and MUST
NOT correlate findings across ordinary runs by hunk-derived public IDs.

#### Scenario: PR 1 issue is fixed in PR 3

- **WHEN** a finding originates in PR 1, remains PRESENT at PR 2, and is ABSENT
  at PR 3
- **THEN** its retained PR 1 lineage is summarized as `FIXED_IN` PR 3

### Requirement: Presence adjudication is strict and bounded

Presence outputs MUST name only supplied lineage IDs and MUST use only
`PRESENT`, `ABSENT`, or `UNCERTAIN`. Missing output MUST vote UNCERTAIN,
PRESENT or ABSENT without nonblank evidence MUST be coerced to UNCERTAIN, a
wave with no valid replicas MUST retry exactly once, and candidates still
uncertain MUST receive one expanded-context pass at twice the initial deadline.

#### Scenario: Candidate is omitted by a valid replica

- **WHEN** a valid presence response omits one supplied lineage
- **THEN** that replica contributes an UNCERTAIN vote for the lineage

#### Scenario: Absence has no evidence

- **WHEN** a response votes ABSENT with whitespace-only evidence
- **THEN** the vote is stored as UNCERTAIN

#### Scenario: Initial result remains uncertain

- **WHEN** no presence value receives a strict majority
- **THEN** only that uncertain lineage receives one expanded-context pass

### Requirement: Lineage summaries preserve transitions

Confirmed origin findings MUST begin PRESENT, unresolved origin findings MUST
begin UNCERTAIN, and summaries MUST be derived from ordered observations. A
final UNCERTAIN observation MUST yield `UNCERTAIN`; otherwise the latest
conclusive PRESENT-to-ABSENT transition MUST yield `FIXED_IN`, the latest
ABSENT-to-PRESENT transition ending in PRESENT MUST yield `REGRESSED_IN`, and a
lineage ending PRESENT without an earlier absence MUST yield `STILL_PRESENT`.

#### Scenario: Finding regresses at the tip

- **WHEN** a lineage history is PRESENT, ABSENT, then PRESENT
- **THEN** the summary is `REGRESSED_IN` at the final member

#### Scenario: Tip presence remains unresolved

- **WHEN** a lineage history is PRESENT, ABSENT, then UNCERTAIN
- **THEN** the summary is `UNCERTAIN` rather than fixed or regressed

### Requirement: Stack publication targets only the tip

Stack publication MUST build one body-only review payload from the persisted
stack report, MUST hardcode `event: COMMENT`, MUST target only the captured tip
pull request, and MUST NOT construct inline comments, approvals, change
requests, or comments on origin members.

#### Scenario: Stack contains findings from PR 1 and PR 2

- **WHEN** a publish payload is built for a stack ending at PR 3
- **THEN** the payload targets PR 3 and contains the stack report only in its
  body

### Requirement: Execute publication revalidates the full stack

Dry-run publication MUST save the payload without a network call. Explicit
`--execute` MUST freshly resolve every member and fail unless repository
identity, open/unmerged state, all base/head refs and SHAs, and every direct
edge equal the persisted manifest immediately before the single COMMENT
request.

#### Scenario: Parent base moves before execution

- **WHEN** any persisted base SHA no longer matches during execute validation
- **THEN** publication fails without creating a GitHub review
