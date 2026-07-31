## Context

Stack manifests already preserve caller-supplied parent-to-child order and pin
each member's current base/head refs and SHAs. The implementation nevertheless
compares the two endpoint trees directly and uses numeric PR comparisons as a
proxy for manifest position. Stack publication revalidates those anchors but
omits the optional GitHub review `commit_id`, leaving a time-of-check/time-of-use
window in which GitHub can select a newer head.

Presence adjudication persists stable SHA-1 lineage IDs. Relaying those 40-byte
identifiers through every model response is unnecessary because a wave only
needs an unambiguous local key. All-invalid retries also currently repeat the
same prompt without telling the model why the previous outputs were rejected.

## Goals / Non-Goals

**Goals:**

- Match ordinary PR merge-base diff semantics for every stack member.
- Make caller/manifest position the only temporal ordering authority.
- Keep persisted lineages strict and verify completed histories against the
  manifest.
- Pin stack publication to the captured tip commit.
- Make presence output validation reject ambiguous duplicates and reduce model
  identifier relay length.
- Make retries self-correcting and partial stack runs recoverable by ID.

**Non-Goals:**

- Changing persisted lineage identity or correlating findings across ordinary
  runs.
- Making GitHub revalidation and review creation one atomic server operation.
- Hardening the prompt-injection surface shared with ordinary review.
- Changing stack publication away from one body-only COMMENT review.

## Decisions

### Member diffs use one three-dot revision

Both content and name-only commands use
`<captured-base-sha>...<captured-head-sha>`. The manifest and
`ResolvedTarget.base_sha` continue to retain the captured base tip; only the
derived review diff changes. This excludes base-only commits when the base
branch advanced after the feature fork and fails naturally if no merge base is
available.

### Observation list order is manifest order

PR numbers remain identities only. A standalone lineage requires its first
observation to match the origin and requires observation PR numbers to be
unique, but it does not compare their numeric values. Presence adjudication
receives the complete manifest member order and requires each candidate's
existing observations to equal the manifest slice from its origin up to, but
not including, the current member. Completed runs additionally verify every
lineage against the full suffix ending at the tip.

This retains the compact existing artifact shape while making the external
manifest, rather than a redundant index or PR-number magnitude, authoritative.

### Presence waves use deterministic local IDs

Each selected wave maps lineages in supplied order to `L1`, `L2`, and so on.
The prompt and strict enum expose only these local IDs. Vote aggregation maps
them back to the stable persisted lineage IDs before constructing observations.
Expanded passes may create a new local mapping for their smaller batch; the
mapping never crosses a wave boundary.

Duplicate local IDs make a runtime response invalid. Missing IDs remain valid
and continue to contribute UNCERTAIN as specified.

### All-invalid retries carry bounded feedback

When every replica in a wave is invalid, the one permitted retry receives each
replica number and its machine-readable `invalid_reason`. The runtime already
bounds these values to internal failure labels, so feedback does not include
model output or arbitrary logs.

### Publication always carries the captured tip commit

`publish_body_review` requires a commit ID and writes it into both dry-run and
execute payloads. The stack CLI passes the manifest tip SHA after execute-mode
revalidation. This prevents GitHub from silently selecting a newer head,
although a fast-forward race can still produce a clearly stale review attached
to the older captured commit.

### Run IDs are announced before model work

Plain output writes the ID to stdout immediately after stack directory
creation. JSON mode writes the early recovery message to stderr so successful
stdout remains one parseable JSON document. The success path does not print a
duplicate plain-text ID.

## Risks / Trade-offs

- [A persisted lineage is manually reordered] → completed-run validation
  compares its full observation sequence with the manifest suffix and fails
  closed.
- [A local ID is confused with a persisted ID] → mapping is private to the
  presence module and outcomes remain keyed only by persisted IDs.
- [Retry reasons do not explain a detailed schema error] → the bounded runtime
  reason still distinguishes format, completion, timeout, and process failures
  without expanding the artifact contract.
- [Early output disrupts JSON consumers] → JSON stdout stays unchanged and the
  recovery ID is emitted on stderr.

## Migration Plan

The feature is not yet merged or released. Existing in-branch stack artifacts
with monotonic PR numbers remain readable. Dry-run payload snapshots gain a
required `commit_id`, and completed lineage artifacts are checked more strictly
against their manifest when reopened.

## Open Questions

None.
