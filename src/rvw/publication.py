"""Human publication derived from diagnostic evidence without mutating artifacts."""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import LaneCoverage
from rvw.i18n import t
from rvw.merge import CollapseGroup, MergeResult
from rvw.presentation import PresentationConfig
from rvw.schema import Severity, Verdict

if TYPE_CHECKING:
    from rvw.summary import RunSummary
    from rvw.synthesis import SynthesisDocument, SynthesisFinding


def plain_text(text: str) -> str:
    """Treat configured plain text as text, not Markdown or HTML instructions."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(text, quote=False))


def evidence_fence(evidence: str) -> str:
    fence = "`" * max(3, max((len(s) + 1 for s in re.findall(r"`+", evidence)), default=0))
    return f"{fence}\n{evidence}\n{fence}"


def _evidence_details(evidence: str, locale: str) -> str:
    return "\n".join(
        [
            "<details>",
            f"<summary>{t('pub.evidence', locale)}</summary>",
            "",
            evidence_fence(evidence),
            "</details>",
        ]
    )


def _synthesis_by_key(synthesis: SynthesisDocument | None) -> dict[str, SynthesisFinding]:
    return {} if synthesis is None else {finding.key: finding for finding in synthesis.findings}


def publication_counts(merged: MergeResult, outcome: AdjudicationOutcome | None) -> tuple[int, int]:
    confirmed = [
        group
        for group in merged.groups
        if outcome is not None and outcome.verdicts.get(group.key) is Verdict.CONFIRMED
    ]
    return (
        sum(group.severity is Severity.BLOCKER for group in confirmed),
        sum(group.severity is not Severity.BLOCKER for group in confirmed),
    )


def uncovered_regions(coverage: Sequence[LaneCoverage]) -> int:
    """Distinct changed regions no lane covered; lane-hunk receipts count each lane again."""
    return len({hunk for lane in coverage for hunk in lane.uncovered})


def failed_lane_ids(coverage: Sequence[LaneCoverage]) -> list[str]:
    """Lane identifiers with a final INVALID planned execution, in coverage order."""
    return [lane.lane_id for lane in coverage if any(not run.valid for run in lane.runs)]


def publication_summary(
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    coverage: Sequence[LaneCoverage],
    presentation: PresentationConfig,
) -> str:
    blockers, warnings = publication_counts(merged, outcome)
    result = t("pub.completed", presentation.locale, b=blockers, w=warnings)
    if uncovered := uncovered_regions(coverage):
        result += " " + t("pub.partial", presentation.locale, n=uncovered)
    if failed := failed_lane_ids(coverage):
        # Lane identifiers are verbatim data; the language gate protects them as identifiers.
        result += " " + t(
            "pub.failed_lanes", presentation.locale, n=len(failed), lanes=", ".join(failed)
        )
    return result


def render_publication_item(
    group: CollapseGroup,
    outcome: AdjudicationOutcome | None,
    *,
    presentation: PresentationConfig,
    synthesis: SynthesisDocument | None = None,
    inline: bool = False,
    synopsis: bool = False,
) -> str:
    locale = presentation.locale
    tag = f"`{group.rule_id}`"
    severity = t("severity." + group.severity.value, locale)
    label = f"**{severity} · {tag}**"
    location = (
        f"{group.file}:{group.line if group.line is not None else t('common.unknown', locale)}"
    )
    synthesized = _synthesis_by_key(synthesis).get(group.key)
    if synthesized is not None:
        parts = [
            f"### {synthesized.title}",
            f"`{location}` · **{severity}** · {tag}",
            synthesized.consequence,
        ]
        if synopsis:
            return "\n\n".join(parts)
        parts[2:2] = [synthesized.what]
        parts.append(synthesized.fix)
        if outcome is not None and (evidence := outcome.evidence.get(group.key, "")):
            parts.append(_evidence_details(evidence, locale))
        return "\n\n".join(parts)

    parts = [label] if inline else [f"### `{location}`", label]
    # Runtime findings have one body field. Its first paragraph is the human title;
    # subsequent paragraphs and the adjudication reason retain impact/correction.
    body = group.bodies[0].strip() if group.bodies else ""
    if body:
        title, separator, detail = body.partition("\n")
        parts.append(title)
        if separator and detail.strip():
            parts.append(detail.strip())
    if outcome is not None:
        reason = outcome.reasons.get(group.key, "")
        if reason and reason not in body:
            parts.append(reason)
        if evidence := outcome.evidence.get(group.key, ""):
            parts.append(evidence_fence(evidence))
    return "\n\n".join(parts)


def render_publication(
    *,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    coverage: Sequence[LaneCoverage] = (),
    presentation: PresentationConfig | None = None,
    synthesis: SynthesisDocument | None = None,
    inline_keys: frozenset[str] = frozenset(),
    summary: RunSummary | None = None,
) -> str:
    presentation = presentation or PresentationConfig()
    locale = presentation.locale
    groups: dict[str, list[CollapseGroup]] = {"blockers": [], "warnings": [], "uncertain": []}
    for group in merged.groups:
        verdict = outcome.verdicts.get(group.key) if outcome is not None else None
        if verdict is Verdict.REJECTED:
            continue
        section = (
            "uncertain"
            if verdict is not Verdict.CONFIRMED
            else "blockers"
            if group.severity is Severity.BLOCKER
            else "warnings"
        )
        groups[section].append(group)
    if synthesis is not None:
        order = {finding.key: index for index, finding in enumerate(synthesis.findings)}
        for selected in groups.values():
            selected.sort(key=lambda group: order.get(group.key, len(order)))
    if synthesis is None:
        parts = [
            t("pub.overall", locale),
            publication_summary(merged, outcome, coverage, presentation),
        ]
    else:
        opening = synthesis.overview
        if synthesis.first_action is not None:
            opening = f"{opening} {synthesis.first_action}"
        parts = [opening, publication_summary(merged, outcome, coverage, presentation)]
    if summary is not None and summary.status.value in {"failed", "degraded"}:
        parts.append(t("pub.incomplete", locale))
    for section, selected in groups.items():
        if section == "uncertain" and not selected:
            continue
        parts.append(t("pub." + section, locale))
        parts.append(
            "\n\n".join(
                render_publication_item(group, outcome, presentation=presentation)
                if synthesis is None
                else render_publication_item(
                    group,
                    outcome,
                    presentation=presentation,
                    synthesis=synthesis,
                    synopsis=group.key in inline_keys,
                )
                for group in selected
            )
            if selected
            else t("pub.empty", locale)
        )
    if presentation.footer:
        parts.append(plain_text(presentation.footer))
    return "\n\n".join(parts) + "\n"
