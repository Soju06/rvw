"""Human gate and stack views separate from their complete diagnostic artifacts."""

from __future__ import annotations

from collections.abc import Sequence

from rvw.adjudicate import AdjudicationOutcome
from rvw.gate import GateVerdict
from rvw.i18n import t
from rvw.merge import MergeResult
from rvw.presentation import PresentationConfig
from rvw.publication import evidence_fence, plain_text, render_publication_item, uncovered_regions
from rvw.schema import Verdict
from rvw.stack import FindingLineage, MemberRunRef, StackManifest


def render_gate_publication(
    verdict: GateVerdict,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    presentation: PresentationConfig | None = None,
) -> str:
    """Publish actionable findings and dispositions, preserving diagnostic JSON."""
    presentation = presentation or PresentationConfig()
    locale = presentation.locale
    lines = [t("pub.gate_heading", locale, verdict=verdict.verdict)]
    groups = {group.key: group for group in merged.groups}
    for item in verdict.findings:
        if item.verdict is Verdict.REJECTED:
            continue
        group = groups.get(item.finding_id)
        if group is not None:
            lines.append(render_publication_item(group, outcome, presentation=presentation))
        else:
            location = (
                f"{item.file}:{item.line if item.line is not None else t('common.unknown', locale)}"
            )
            lines.extend(
                [
                    f"### `{location}`",
                    f"**{t('severity.' + item.severity.value, locale)} · `{item.rule_id}`**",
                ]
            )
        lines.append(t("pub.disposition." + item.disposition.value, locale))
        lines.append(item.reason)
    if not verdict.findings:
        lines.append(t("pub.empty", locale))
    if verdict.kind != "completed" or verdict.failures:
        lines.append(t("pub.incomplete", locale))
    if uncovered := uncovered_regions(verdict.coverage):
        lines.append(t("pub.partial", locale, n=uncovered))
    if presentation.footer:
        lines.append(plain_text(presentation.footer))
    return "\n\n".join(lines).rstrip() + "\n"


def render_stack_publication(
    manifest: StackManifest,
    member_runs: Sequence[MemberRunRef],
    lineages: Sequence[FindingLineage],
    presentation: PresentationConfig | None = None,
) -> str:
    """Publish finding histories with human state labels and verbatim evidence."""
    presentation = presentation or PresentationConfig()
    locale = presentation.locale
    lines = [t("pub.stack_heading", locale)]
    if {member.number for member in manifest.members} - {run.pr_number for run in member_runs}:
        lines.append(t("pub.incomplete", locale))
    for lineage in lineages:
        location = f"{lineage.file}:{lineage.line if lineage.line is not None else t('common.unknown', locale)}"
        state = t("pub.state." + lineage.state.value, locale)
        if lineage.state_pr is not None:
            state += f" · PR #{lineage.state_pr}"
        lines.extend(
            [
                f"### `{location}`",
                f"**{t('severity.' + lineage.severity.value, locale)} · `{lineage.rule_id}`**",
                state,
                *lineage.bodies,
            ]
        )
        for observation in lineage.observations:
            lines.append(f"#### PR #{observation.pr_number}")
            lines.append(t("pub.presence." + observation.presence.value, locale))
            if observation.reason:
                lines.append(observation.reason)
            if observation.evidence:
                lines.append(evidence_fence(observation.evidence))
    if not lineages:
        lines.append(t("pub.empty", locale))
    if presentation.footer:
        lines.append(plain_text(presentation.footer))
    return "\n\n".join(lines).rstrip() + "\n"


__all__ = ["render_gate_publication", "render_stack_publication"]
