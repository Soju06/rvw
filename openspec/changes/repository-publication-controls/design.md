## Context

See proposal.md. Python persists review facts and presentation; the Worker bootstraps from the captured base and consumes strict process/summary contracts. A sibling lane owns webhook eligibility.

## Goals / Non-Goals

Goals: repository-owned controls, backward-compatible defaults, deterministic placement, strict parsing and localized human output.
Non-goals: changing judgments, triggers, language ratios, thread identity, registry, deployment or publication event semantics.

## Decisions

- Fix P1/P2 first with generic localized examples and source-aware process patterns. Treat a vocabulary occurrence in any review source as domain evidence; allowed_terms bypasses vocabulary bans only.
- Extend strict nested presentation and publish models with legacy defaults. Explicit channels override publish_state; absent channels map none to checks. Zero inline cap is supported as body-only publication.
- Resolve Worker publication controls from the base ref before building execution arguments. Mandatory checks always terminalize; advisory checks cannot turn invalid/infra into success.
- Select inline candidates once using severity then stable identity for capped selection. Keep default encounter order for unlimited placement. Use the selected inline keys for body synopsis selection and thread write eligibility; keep body-only findings in identity matching to prevent false fix evidence, then withhold their thread actions. All other findings retain full bodies.
- Keep catalogs focused on human text; preserve machine contracts. Extend checked-in schemas and cross-language fixtures.

## Risks / Trade-offs

- Domain vocabulary exemption is review-wide → still validate protected literals and evidence fidelity per finding.
- Thread matching can suppress candidates → render full body for findings that do not actually post inline.
- Older contracts lack new fields → parsers supply current defaults.
- Shared-file conflicts → minimal edits, no trigger-area changes, report all shared files.

## Migration Plan

No repository configuration changes are required. Consumers opt into new keys at the base revision. Reverting configuration restores defaults. No external registry edits or rollout are included.

Worker parsing uses the pinned `yaml` package for nested policy lists and strict scalar inspection. Its policy reader uses YAML 1.1 semantics to match PyYAML; explicit null is not an omitted field, and float scalars cannot satisfy integer caps.
