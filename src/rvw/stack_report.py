"""Deterministic file-first Markdown reporting for stacked PR reviews."""

from __future__ import annotations

from collections.abc import Sequence

from rvw import __version__
from rvw.i18n import Locale, t
from rvw.presentation import PresentationConfig
from rvw.stack import FindingLineage, MemberRunRef, StackManifest


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _state_label(lineage: FindingLineage) -> str:
    if lineage.state_pr is None:
        return lineage.state.value
    return f"{lineage.state.value} #{lineage.state_pr}"


def render_stack_report(
    manifest: StackManifest,
    member_runs: Sequence[MemberRunRef],
    lineages: Sequence[FindingLineage],
    *,
    locale: Locale = "en",
    presentation: PresentationConfig | None = None,
) -> str:
    """Render PR-local ordinary results and cross-head lineage history separately."""

    if presentation is not None:
        locale = presentation.locale
    display_name = presentation.display_name if presentation is not None else "rvw"
    run_by_pr = {item.pr_number: item for item in member_runs}
    lines = [
        t("stack.header", locale, display_name=display_name),
        "",
        t("stack.run", locale, p0=manifest.run_id),
        t("stack.repository", locale, p0=manifest.repo),
        t("stack.tip", locale, p0=manifest.members[-1].number, p1=manifest.members[-1].head_sha),
        "",
        t("stack.members_heading", locale),
        "",
        t("stack.members_columns", locale),
        "| ---: | --- | --- | --- |",
    ]
    lines.extend(
        (
            f"| [#{member.number}]({member.url}) | {_cell(member.title)} | "
            f"`{member.base_ref}` / `{member.base_sha}` | "
            f"`{member.head_ref}` / `{member.head_sha}` |"
        )
        for member in manifest.members
    )
    lines.extend(["", t("stack.local_heading", locale)])
    for member in manifest.members:
        run = run_by_pr.get(member.number)
        lines.extend(["", t("stack.local_result", locale, p0=member.number), ""])
        if run is None:
            lines.append(t("stack.missing", locale))
            continue
        lines.extend(
            [
                t("stack.member_run", locale, p0=run.run_id),
                t("stack.member_report", locale, p0=run.report_path),
                "",
                t("stack.verdict_columns", locale),
                "| --- | ---: |",
                f"| CONFIRMED | {run.verdict_counts['CONFIRMED']} |",
                f"| REJECTED | {run.verdict_counts['REJECTED']} |",
                f"| UNCERTAIN | {run.verdict_counts['UNCERTAIN']} |",
            ]
        )

    lines.extend(["", t("stack.lineage_heading", locale), ""])
    if not lineages:
        lines.append(t("stack.empty", locale))
    for lineage in lineages:
        location = f"{lineage.file}:{lineage.line if lineage.line is not None else t('common.unknown', locale)}"
        pr_timeline = " → ".join(
            f"PR #{observation.pr_number}" for observation in lineage.observations
        )
        presence_timeline = " → ".join(
            observation.presence.value for observation in lineage.observations
        )
        lines.extend(
            [
                f"### {_state_label(lineage)} — `{lineage.rule_id}`",
                "",
                t("stack.lineage", locale, p0=lineage.lineage_id),
                t(
                    "stack.origin",
                    locale,
                    p0=lineage.origin_pr,
                    p1=lineage.origin_run_id,
                    p2=lineage.origin_finding_id,
                ),
                t("stack.location", locale, p0=location),
                t("stack.severity", locale, p0=lineage.severity.value),
                t("stack.timeline", locale, p0=pr_timeline),
                t("stack.presence", locale, p0=presence_timeline),
                "",
                t("stack.claim_heading", locale),
                "",
                *lineage.bodies,
                "",
                t("stack.evidence_heading", locale),
                "",
                t("stack.evidence_columns", locale),
                "| ---: | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            (
                f"| #{observation.pr_number} | {observation.presence.value} | "
                f"{_cell(', '.join(vote.value for vote in observation.replica_votes) or '—')} | "
                f"{_cell(observation.reason or '—')} | {_cell(observation.evidence or '—')} |"
            )
            for observation in lineage.observations
        )
        lines.append("")

    lines.extend(["---", "", t("stack.footer", locale, p0=__version__, display_name=display_name)])
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_stack_report"]
