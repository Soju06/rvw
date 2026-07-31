## MODIFIED Requirements

### Requirement: Every member uses the ordinary review pipeline

Stack review MUST execute the common DISCOVER, MERGE, ADJUDICATE, and REPORT
pipeline exactly once for every member in caller order and MUST persist each
ordinary run ID after that member completes. Each member's review diff and
changed paths MUST compare the captured head against the merge base of the
captured base and head, matching ordinary pull-request diff semantics.

#### Scenario: Third member review fails operationally

- **WHEN** the first two ordinary reviews complete and the third fails
- **THEN** `member-runs.json` retains the first two run references and no
  completed stack report is emitted

#### Scenario: A member base advances after the feature fork

- **WHEN** the captured base contains commits that are not ancestors of the
  captured member head
- **THEN** the member review excludes those base-only changes rather than
  presenting them as reverse deletions

### Requirement: Presence adjudication is strict and bounded

Presence outputs MUST use deterministic batch-local IDs for supplied lineages,
MUST name only those supplied IDs, MUST contain no duplicate IDs, and MUST use
only `PRESENT`, `ABSENT`, or `UNCERTAIN`. The system MUST map local IDs back to
persisted lineage IDs without requiring the model to relay stable SHA-1 IDs.
Missing output MUST vote UNCERTAIN, PRESENT or ABSENT without nonblank evidence
MUST be coerced to UNCERTAIN, a wave with no valid replicas MUST retry exactly
once with the prior replicas' machine-readable invalid reasons in the prompt,
and candidates still uncertain MUST receive one expanded-context pass at twice
the initial deadline.

#### Scenario: Candidate is omitted by a valid replica

- **WHEN** a valid presence response omits one supplied local lineage ID
- **THEN** that replica contributes an UNCERTAIN vote for the persisted lineage

#### Scenario: Replica repeats a local lineage ID

- **WHEN** one presence response contains the same batch-local lineage ID twice
- **THEN** that response is invalid rather than silently retaining one item

#### Scenario: All replicas are invalid

- **WHEN** every presence replica in a wave returns an invalid result
- **THEN** the one retry prompt identifies each prior replica's invalid reason

#### Scenario: Absence has no evidence

- **WHEN** a response votes ABSENT with whitespace-only evidence
- **THEN** the vote is stored as UNCERTAIN

#### Scenario: Initial result remains uncertain

- **WHEN** no presence value receives a strict majority
- **THEN** only that uncertain lineage receives one expanded-context pass

### Requirement: Lineage summaries preserve transitions

Confirmed origin findings MUST begin PRESENT, unresolved origin findings MUST
begin UNCERTAIN, and summaries MUST be derived from unique observations ordered
by manifest position rather than numeric PR value. A completed lineage's
observation PRs MUST equal the manifest suffix from its origin through the tip.
A final UNCERTAIN observation MUST yield `UNCERTAIN`; otherwise the latest
conclusive PRESENT-to-ABSENT transition MUST yield `FIXED_IN`, the latest
ABSENT-to-PRESENT transition ending in PRESENT MUST yield `REGRESSED_IN`, and a
lineage ending PRESENT without an earlier absence MUST yield `STILL_PRESENT`.

#### Scenario: Child PR number is lower than its parent

- **WHEN** a valid caller-ordered direct chain is supplied as `--prs 20,15`
- **THEN** observations for PR 20 then PR 15 are accepted in that manifest order

#### Scenario: Finding regresses at the tip

- **WHEN** a lineage history is PRESENT, ABSENT, then PRESENT
- **THEN** the summary is `REGRESSED_IN` at the final member

#### Scenario: Tip presence remains unresolved

- **WHEN** a lineage history is PRESENT, ABSENT, then UNCERTAIN
- **THEN** the summary is `UNCERTAIN` rather than fixed or regressed

### Requirement: Execute publication revalidates the full stack

Dry-run publication MUST save the payload without a network call. Every stack
publication payload MUST include the captured tip head SHA as `commit_id`.
Explicit `--execute` MUST freshly resolve every member and fail unless
repository identity, open/unmerged state, all base/head refs and SHAs, and every
direct edge equal the persisted manifest immediately before the single
commit-pinned COMMENT request.

#### Scenario: Parent base moves before execution

- **WHEN** any persisted base SHA no longer matches during execute validation
- **THEN** publication fails without creating a GitHub review

#### Scenario: Tip moves between validation and publication

- **WHEN** the tip head changes after revalidation but before GitHub processes
  the review request
- **THEN** the request still identifies the captured tip commit and cannot
  silently attach the review to the newer head

## ADDED Requirements

### Requirement: Partial stack runs expose a recovery ID

Stack review MUST emit its stack run ID immediately after creating the run
directory and before member model work. Plain output MUST emit the ID on stdout,
while JSON mode MUST preserve a single JSON document on stdout and emit the
early recovery ID on stderr.

#### Scenario: First member review fails

- **WHEN** stack directory creation succeeds and the first member later fails
- **THEN** the operator has already received the stack run ID needed to inspect
  the partial artifacts
