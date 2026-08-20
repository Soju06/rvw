# Post-discovery prompt cost change context

## Purpose and scope

This document records the measured basis and compatibility boundaries for bounding
post-discovery prompt content. Normative behavior is in the adjacent delta
specifications.

## Measured basis

- A fixture containing `pnpm-lock.yaml`, `dist/bundle.js`, and `src/app.py` produced
  `kept_chars` of 398 and `excluded_chars` of 14,390. The adjudication prompt built
  from the same target contained both excluded paths and the raw diff verbatim, giving
  the adjudicator 37.2 times the characters discovery retained.
- A production run observed on 2026-08-20 passed a 112,000-character diff to
  adjudication. At the default three replicas that is 336,000 characters per wave for
  the diff alone. An all-invalid retry followed by an uncertain expanded pass and its
  own retry bounds one adjudication at twelve full-diff prompts, or 1,344,000
  characters.
- A seven-member stack simulation with ten confirmed findings per member and a
  100,000-character diff accumulated 2,677,698 prompt characters across presence
  recheck waves, of which 1,800,972 were repeated diff content.
- `openspec/specs/discovery/spec.md` bounds a retained chunk at 400,000 characters.
  Adjudication bypasses the chunk planner entirely, so that bound does not currently
  apply to any post-discovery prompt.

## Key decisions

- `openspec/specs/adjudication/spec.md` already says a replica receives "the reviewed
  diff". This change makes the implementation match that phrase rather than widening
  the contract.
- `openspec/specs/stack-review/spec.md` already requires presence retry prompts to
  name prior invalid reasons. Discovery and adjudication adopt that established
  contract instead of a new one.
- Adjudication and presence prompts stay unchunked. Verdict evidence may live in any
  kept file, so partitioning them would change verdict semantics rather than remove
  waste.

## Explicitly rejected

- Token, turn, or tool-call ceilings on `codex exec`. `DECISIONS.md` records the owner
  decision that cost is not a constraint and only speed and review quality matter. A
  turn ceiling would cut verification depth, which is the opposite trade.
- Lowering the adjudication replica default from three. ADR-007 and
  `openspec/specs/adjudication/context.md` derive that default from a measured
  nine-candidate fixture and a 26-run production sample.
- Flattening the doubled expanded-pass deadline.
  `openspec/changes/expose-runtime-deadline/design.md` records that this was considered
  and rejected, and its `context.md` documents the resulting 3600-second maximum as an
  accepted bounded outcome. An earlier reading of that maximum as a ceiling violation
  was incorrect.

## Constraints

- The reviewed diff must equal discovery's chunk content byte-for-byte whenever the
  retained diff fits one chunk.
- Exclusion policy stays owned by `diffbudget`; no caller re-implements globs or size
  bounds.
- Retry feedback appears only on a replacement wave, never on an initial wave.
- Reviewed-diff accounting is a prompt input and is not added to persisted schemas.

## Failure modes

- Filtering only one of the two post-discovery prompt builders leaves the amplification
  in place for the other stage.
- Omitting the exclusion header could let an adjudicator treat withheld content as
  absent content and quote that absence as evidence.
- Emitting retry feedback unconditionally would change every first-wave prompt and
  invalidate prompt-stability regressions.

## Concrete example

For a target whose diff contains one lockfile, one `dist/**` bundle, and one source
file, discovery reviews only the source segment behind an exclusion header. After this
change, adjudication and stack presence recheck receive that same header plus that same
source segment. When every initial replica of a wave is INVALID, the single retry prompt
additionally lists each prior replica's machine-readable invalid reason.
