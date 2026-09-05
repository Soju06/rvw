---
lane: hygiene
tier: base
schedule_hint: normal
severity_cap: blocker
validation: pending
---

# hygiene

Find mechanical defects visible in the change and its immediate context.
Report a concrete failure or inconsistency, never a style preference.

## rule: slop/sot-violation

A value or shape with an established source of truth must remain derived from that
source. Hand-copied or shadowed declarations diverge as the source changes. Identify the
authoritative definition and compare the duplicate with its consumers; show the lost
derivation or conflicting value.

## rule: slop/untraceable-fallback

A fallback must preserve the original failure provenance. A swallowed cause or silent
default can leave the resulting state impossible to diagnose. Trace a concrete failing
operation through its fallback and show which cause information is lost.

## rule: slop/excessive-fallback

Fallbacks must represent legitimate alternate states rather than mask an impossible
state or a required dependency failure. Masking those failures lets execution continue
with invalid assumptions. Trace the preconditions and show why the fallback cannot
produce a valid result.

## rule: slop/name-guess-fallback

A consumer must use the producer's declared field mapping rather than guess several
spellings of the same field. Guessing hides a broken boundary and can select stale data.
Compare producer and consumer names and identify the inconsistent mapping and resulting
value.

## rule: slop/duplicate-object-key

A declaration must not accidentally repeat a key or name that replaces an intended
value. Silent replacement changes the effective data. Resolve duplicate declarations in
evaluation order and identify the value that is lost.

## rule: slop/dead-assignment

An assignment must not accidentally overwrite a required value before any use. Such
remnants can discard intended work or supply the wrong value later. Trace writes and
reads and identify the unintended overwrite and its consequence.

## rule: slop/copy-paste-remnant

Copied logic must refer to the intended entity and operation at its new site. A leftover
identifier or branch can apply work to the wrong target. Compare the new site with its
source and trace the remnant to an incorrect result.

## rule: slop/both-paths-kept

A replacement must not accidentally execute both old and new paths for the same
operation. The duplicate execution can repeat effects or conflict over state. Trace the
dispatch conditions and show both paths executing; intentional staged transitions with
distinct ownership are not defects.
