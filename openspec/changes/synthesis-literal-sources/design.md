## Context

See proposal.md for the observed Korean failures. The validator currently shares a broad technical-token extractor between invention detection and language/vocabulary protection. Runtime synthesis has the resolved target, while retained validation loads only merge/outcome/presentation.

## Goals / Non-Goals

Goals: accept the two supplied live documents using deterministic fixtures, preserve exact identifier/path matching, and keep source scope equal across runtime and replay.

Non-goals: changes to schemas, judgments, runtime budgets, retries, fallback reasons, language thresholds, forbidden vocabulary or external registry.

## Decisions

- Keep broad technical extraction for protection and introduce a narrow backtick/path extractor for invention checks. An acronym allowlist would be incomplete and would keep confusing prose with code.
- Pass optional resolved target context into validation; runtime supplies its target and replay loads the saved target. PR title/body join each finding's sources and are independently available to empty-findings openings.
- Match individual source texts after whitespace collapse with existing token boundaries. Do not lowercase, remove underscores, or concatenate separate sources to manufacture a match.
- Add composed location literals from each finding's path/line and explicit line references in its evidence. Ordinary numeric code values are not evidence line references. Keep locations scoped to the same finding.
- Keep broad source literals for vocabulary exemption and language protection. Protect bare code identifiers in output for language checking without making them invention candidates; quoted source error strings remain protected.

## Risks / Trade-offs

- Unbackticked identifiers no longer receive invention checks, as explicitly requested; the prompt continues requiring technical literals in backticks.
- Whitespace equivalence intentionally does not prove semantic equivalence of code. Case, punctuation and underscores stay significant, and matching stays within one source text.
- Artifact fixtures may contain irrelevant runtime details → retain verbatim output JSON plus only merged source fields, outcome maps and PR title/body needed for validation.
