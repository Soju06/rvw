---
lane: agent-tools
tier: scope
schedule_hint: heavy
severity_cap: blocker
validation: pending
when:
  paths:
  - '**/tools/**'
  - 'tools/**'
  - '**/tool/**'
  - 'tool/**'
  - '**/toolpacks/**'
  - 'toolpacks/**'
  - '**/*tool*.ts'
  - '*tool*.ts'
  - '**/*tool*.py'
  - '*tool*.py'
---

# agent-tools

Review LLM tool contracts: provider-compatible schemas, model-facing instructions,
and values relayed between calls. These patterns declare tool-definition conventions;
repositories with other layouts need project lanes. Findings belong to changed tool
definitions, schema serializers, dispatch or feedback in the matching paths.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: agent-tool/unsupported-schema-construct

The wire schema must be accepted and enforced by the tool's configured providers.
Unsupported keywords can reject calls or silently erase constraints. Inspect the
serializer and the declared provider capability profile: root shape/composition,
references, defaults, constants, patterns, numeric constraints, depth and name limits.
Report the precise construct and provider incompatibility with evidence; do not assume
one universal blacklist. Nested anyOf is a defect only where the target profile forbids
it.

## rule: agent-tool/ambiguous-optionality

Optional/nullable/list fields where the model cannot tell what "not providing" looks
like: is it `null`, omit the field, or `[]`? Flag any optional field whose absent-value
convention is not pinned down in the schema (defaults declared, null vs omit vs empty
explicitly resolved). Models reliably confuse these three. Also flag dishonest
`required`: params marked required that the caller may not have — models hallucinate
plausible values for required fields the user never mentioned. Required must be honest
and minimal. Verify the omitted, null and empty cases against the schema and handler.

## rule: agent-tool/needless-llm-choice

Decisions delegated to the LLM that the system can resolve deterministically: enum
parameters the caller already knows, "mode" flags derivable from context,
ordering/formatting choices with one correct answer. Every removable choice is removed
error surface. Trace the source of each choice and show the deterministic value already
available to the caller.

## rule: agent-tool/stale-or-sloppy-description

Tool or field descriptions that are missing, wrong after a behavior change (stale), or
so thin the model must guess semantics. Compare the description with accepted values and
implementation; show the incorrect call or selection it invites.

## rule: agent-tool/scoped-detail-in-global-tool

The inverse failure: case-specific instructions written into an always-loaded global
tool description, or descriptions bloated with edge-case prose that taxes every call.
Global surface gets the general contract; specific cases belong in scoped docs/prompts.
Trace when the description is loaded and show irrelevant instructions affecting
unrelated calls.

## rule: agent-tool/unrecoverable-error-feedback

Tool error feedback must tell the model which supplied field was invalid, why, and how
to obtain a valid value when recovery is possible. Opaque validation feedback makes the
next attempt repeat the failure. Trace a rejected input to its model-visible response
and verify that a caller can correct it without guessing. Generic swallowed-error
provenance belongs to hygiene; report only the missing tool recovery contract here.

## rule: agent-tool/noisy-output

Tool OUTPUT is prompting surface, same as the description. Flag outputs carrying
information the model does not need: debug dumps, internal ids/fields never consumed
downstream, redundant envelope repetition, unpaginated bulk payloads. Every needless
output token taxes the model's context on every call. Trace output fields to model
decisions and follow-up consumers; identify the unused payload and its repeated context
burden.

## rule: agent-tool/complex-value-relay

Parameters that make the model combine, normalize, reformat, or derive values when
relaying them between calls (puzzle contracts). A follow-up tool must accept EXACTLY
what the earlier tool returned, same field name, verbatim. Flag any contract where the
model must assemble `"tokyo/A1301"` from `area` + `code`, strip prefixes, or re-encode
values. Compare the producer response to the next input schema and show the
transformation required of the model.

## rule: agent-tool/high-entropy-token-relay

Requiring the model to transcribe LONG random/opaque strings verbatim between calls
(session tokens, UUIDs over ~20 chars, signed URLs, base64 blobs). Models mistranscribe
high-entropy strings at a meaningful rate. Prefer short ids, indices into a returned
list, or system-side resolution; flag every contract whose failure mode is "the model
retyped a random string wrong". Trace the returned opaque value to its next input and
verify whether the system can relay it without model transcription.

## rule: agent-tool/lenient-coercion-union

A type-coercion bug "fixed" by widening the schema instead of failing closed: `boolean |
"true" | "false"` unions, implicit coercion on agent-facing fields, accepting
aliases/variant spellings of typed values. This duplicates the contract, propagates to
every downstream consumer of the generated schema, and diverges this tool's value
representation from its siblings (a selection-confusion source in itself). The correct
fix is a strict type that rejects the malformed value with an actionable error so the
model self-corrects. Flag any schema union whose extra branches exist only to absorb
type mistakes. Compare the accepted branches and downstream types and show the malformed
value admitted solely by coercion.

## rule: agent-tool/open-set-enum

Enum used on a set that is not genuinely closed: high-cardinality vocabularies, values
that grow with data (place names, product categories, provider ids), or lists already
stale against the backing source. Open sets belong in a plain string plus a
resolver/lookup operation; enums are for small stable sets, where they are the strongest
constraint available. Also flag numeric enums where string enums are portable. Compare
the declared enum with its backing vocabulary and provider profile; identify stale
values or a portability failure.

## rule: agent-tool/undiscoverable-vocabulary

The dual of open-set-enum: a plain string (or pattern-only) input whose valid values the
model has NO in-band path to obtain. For every such field demand at least one of: (a) a
closed enum, (b) a discovery/resolver operation returning the value under the SAME field
name, (c) an earlier response field that feeds it verbatim, or (d) a complete example
list in the description. None of the four ⇒ dead parameter: schema-valid, never 400s,
effectively non-functional because callers cannot learn its vocabulary. Two "such as X"
examples are not a path (vocabulary size and the remaining values stay unknowable). A
live probe returning 200 proves nothing — the prober already knew the value. Display-
name response fields (e.g. localized labels) do NOT count as feedback for slug/code
inputs unless the mapping is returned too. Trace all in-band discovery and response
paths and identify a valid input the model cannot obtain.

## rule: agent-tool/breaking-schema-evolution

Changes to a shipped tool must preserve the inputs and response values that existing
callers still use. A newly required parameter, repurposed field, or renamed/retyped
relay field can break calls in flight. Compare old and new schemas, descriptions and
consumers and show an existing valid call or relay that now fails or changes meaning.
