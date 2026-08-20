## Why

Discovery filters generated and oversized files out of the review diff, but every
stage after discovery re-embeds the unfiltered `target.diff`. Adjudication
(`src/rvw/adjudicate.py`) and stack presence recheck (`src/rvw/stack_adjudicate.py`)
both send the raw diff, so lockfiles, `dist/**` bundles, and per-file segments above
200,000 characters return to the prompt that discovery deliberately excluded them
from. A measured fixture with two excluded files and one kept file gives adjudication
37.2 times the characters discovery retained, and the default three adjudication
replicas send that prompt three times per wave.

`openspec/specs/adjudication/spec.md` already requires each replica to receive "the
reviewed diff". The reviewed diff is the budget-filtered content, so the current
implementation contradicts its own contract while spending tokens on content no lane
was allowed to review.

Separately, `stack-review` requires an all-invalid presence retry to carry the prior
replicas' machine-readable invalid reasons, and `src/rvw/stack_adjudicate.py`
implements that. The equivalent discovery and adjudication retries re-send a
byte-identical prompt with no failure signal, so a schema-shaped failure is likely to
repeat and waste the whole wave.

## What Changes

- Add a shared reviewed-diff helper that applies the existing generated-path and
  oversized-file exclusions and returns one contiguous filtered diff plus its exact
  character accounting.
- Make adjudication and stack presence recheck build their prompts from that reviewed
  diff instead of the raw target diff, preserving byte-for-byte equality with
  discovery's content whenever discovery planned a single chunk.
- Carry each prior replica's machine-readable invalid reason into the one all-invalid
  retry prompt for discovery dispatch and for adjudication, matching the existing
  stack-presence retry contract.
- Add deterministic regressions proving excluded content never reaches an
  adjudication or presence prompt and that both retry paths name their prior invalid
  reasons.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `adjudication`: Define the reviewed diff supplied to replicas as the
  budget-filtered diff and require the all-invalid retry to carry prior invalid
  reasons.
- `discovery`: Require the one all-lane replacement wave to carry prior invalid
  reasons, and define the reviewed-diff projection alongside the existing chunk
  planner.
- `stack-review`: Require presence recheck prompts to use the budget-filtered
  descendant diff.

## Impact

Affected implementation includes `src/rvw/diffbudget.py`, `src/rvw/adjudicate.py`,
`src/rvw/stack_adjudicate.py`, `src/rvw/dispatch.py`, and `src/rvw/prompts.py`. Tests
and the adjudication, discovery, and stack-review specifications change. Persisted run
and report schemas, the external runtime registry, replica and concurrency defaults,
deadline behavior, model selection, version, lockfile, and dependencies do not change.

## Non-Goals

- Adding token, turn, or tool-call ceilings to `codex exec`. `DECISIONS.md` records
  the owner decision that review quality and speed outrank cost, and such a ceiling
  would trade verdict quality for spend.
- Changing the adjudication replica default of three, which
  `openspec/specs/adjudication/spec.md` and ADR-007 establish from measurement.
- Changing the doubled expanded-pass deadline. `openspec/changes/expose-runtime-deadline/design.md`
  records that flattening it was considered and rejected, and its 3600-second maximum
  is a documented bounded outcome rather than a defect.
- Chunking the adjudication or presence prompt. A candidate may depend on any kept
  file, so splitting these prompts would change verdict semantics rather than remove
  waste.
