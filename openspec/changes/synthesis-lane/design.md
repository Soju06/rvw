## Context

See proposal.md for the publication problem. Ordinary review persists target, discovery, merge and adjudication before reporting. Codex already supports tool-less raw execution, strict output validation, policy resolution, per-attempt telemetry and the review egress boundary. The publication view is separate from diagnostic report.md.

## Goals / Non-Goals

Goals: explain confirmed evidence in the repository's language and voice; preserve finding identity and source literals; keep body counts consistent; degrade gracefully when synthesis is unavailable.

Non-goals: discovery, adjudication, event selection, reconciliation, runtime policy/deadline defaults, special gate/stack rendering, external registry, deployment surfaces, or publication of this branch.

## Decisions

- Introduce a strict synthesis document with overview, nullable first_action, and keyed title/what/consequence/fix records. Severity and anchors remain exclusively in merge/outcome artifacts. Include all non-rejected groups, preserving uncertainty explicitly; this interprets the brief's ambiguous “non-REJECTED confirmed finding” consistently with its no-dropped-findings rule and current uncertain publication section.
- Read target metadata using the persisted PR metadata already supplied to dynamic lanes. Load all input stage files and presentation snapshot immediately before synthesis; pass only relevant text, never a fresh diff or tools.
- Use a tool-less runtime carrying the resolved Codex policy and watchdog, with a 120-second per-attempt budget capped by the requested lane deadline. Invoke once normally; retry only invalid JSON/schema/fidelity output once with validation diagnostics. Runtime/process failures fall back immediately. Preserve cancellation. No review status or policy verdict changes on synthesis failure.
- Validate exact key coverage and duplicates in addition to strict JSON. Reject internal reviewer vocabulary outside protected source literals. Preserve source paths and quoted identifiers/error strings verbatim; supply literal protection to the existing language gate. Evidence remains separately rendered from persisted outcome data.
- Persist synthesis.json only for a validated document. Persist status and telemetry in run health and execution summary, including fallbacks and legacy absence. Report synthesis uses the operator file first, then the lane overview/first action; other diagnostic sections remain unchanged.
- Synthesized findings posted inline have short body entries (title/location and consequence); other body entries and inline items carry the full explanation with localized collapsed evidence. Without synthesis, all non-rejected findings retain existing full rendering. Keep marker generation and reconciliation unchanged.
- Add strict nested voice defaults engineers/formal with optional guidance of at most 800 Unicode characters. Extend the Worker's bounded YAML parser for the voice mapping and multiline guidance with shared parity fixtures; preserve the established presentation_config_invalid reason.

## Risks / Trade-offs

- Model prose can drift beyond evidence → prompt restricts claims, schema forbids identity/severity changes, deterministic fidelity checks guard keys/literals/internal terminology, and publication still passes the language gate.
- Additional latency → one small tool-less attempt, one content-validation retry only, existing watchdog and telemetry.
- Legacy artifacts lack synthesis/voice → documented defaults and current human rendering remain valid.
- Source literals can contain forbidden words → protect source code/literals before testing reviewer vocabulary, so valid identifiers are never translated or censored.
