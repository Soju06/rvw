"""Deterministic localized diagnostic review reports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from rvw import __version__
from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport
from rvw.discover import LaneCoverage
from rvw.i18n import Locale, t
from rvw.merge import CollapseGroup, MergeResult, PatternFold, RegionFold
from rvw.presentation import PresentationConfig
from rvw.provenance import current_build_provenance
from rvw.schema import Verdict
from rvw.summary import ReviewStatus, RunSummary
from rvw.target import ResolvedTarget


def _target_label(target: ResolvedTarget, *, locale: Locale = "en") -> str:
    if target.kind == "pr":
        return f"PR#{target.pr_number}"
    if target.kind == "commit":
        return t("target.commit", locale, p0=target.head_sha[:9])
    return t("target.uncommitted", locale)


def _region_label(
    fold: RegionFold, groups: dict[str, CollapseGroup], *, locale: Locale = "en"
) -> str:
    lines = [line for key in fold.group_keys if (line := groups[key].line) is not None]
    return t("report.region", locale, p0=fold.file, p1=min(lines), p2=max(lines))


def _votes(outcome: AdjudicationOutcome | None, key: str, *, locale: Locale = "en") -> str:
    if outcome is None:
        return t("report.unadjudicated", locale)
    return "/".join(verdict.value for verdict in outcome.replica_votes.get(key, [])) or t(
        "common.none", locale
    )


def render_group_item(
    group: CollapseGroup,
    outcome: AdjudicationOutcome | None,
    *,
    region_labels: Sequence[str] = (),
    locale: Locale = "en",
) -> str:
    """Render one non-folded finding item for reports and inline publication."""

    line = group.line if group.line is not None else t("common.unknown", locale)
    suffix = "" if not region_labels else f" {' '.join(region_labels)}"
    parts = [
        f"### [{group.severity.value}] {group.rule_id} — {group.file}:{line}{suffix}",
        t("report.finding_id", locale, p0=group.key),
        t(
            "report.agreement",
            locale,
            p0=group.agreement,
            p1=_votes(outcome, group.key, locale=locale),
        ),
    ]
    if outcome is not None:
        reason = outcome.reasons.get(group.key, "")
        evidence = outcome.evidence.get(group.key, "")
        if reason:
            parts.append(t("report.reason", locale, p0=reason))
        if evidence:
            parts.extend([t("report.evidence", locale), f"```\n{evidence}\n```"])
    if group.bodies:
        parts.append(group.bodies[0])
    return "\n\n".join(parts)


def _render_pattern_item(
    fold: PatternFold,
    groups: dict[str, CollapseGroup],
    outcome: AdjudicationOutcome | None,
    priority_index: dict[str, int],
    region_labels: Sequence[str],
    *,
    locale: Locale = "en",
) -> str:
    representative = groups[fold.group_keys[0]]
    members = sorted(
        (groups[key] for key in fold.group_keys), key=lambda item: priority_index[item.key]
    )
    highest = members[0]
    if outcome is None:
        member_content = {
            member.key: member.bodies[0].strip() if member.bodies else "" for member in members
        }
    else:
        member_content = {
            member.key: outcome.reasons.get(member.key, "").strip() for member in members
        }
    differing_content = len(set(member_content.values())) > 1

    suffix = "" if not region_labels else f" {' '.join(region_labels)}"
    parts = [t("report.pattern", locale, p0=fold.rule_id, p1=fold.repetition, p2=suffix)]
    parts.extend(
        (
            t(
                "report.pattern_member",
                locale,
                p0=member.file,
                p1=member.line if member.line is not None else t("common.unknown", locale),
                p2=member.key,
            )
        )
        for member in members
    )
    if fold.shared_identifiers:
        identifiers = ", ".join(f"`{identifier}`" for identifier in fold.shared_identifiers)
        parts.append(t("report.shared_identifiers", locale, p0=identifiers))
    parts.append(
        t(
            "report.agreement",
            locale,
            p0=highest.agreement,
            p1=_votes(outcome, highest.key, locale=locale),
        )
    )

    if differing_content:
        for member in members:
            line = member.line if member.line is not None else t("common.unknown", locale)
            parts.append(f"**{member.file}:{line}** — {member_content[member.key]}")
            if outcome is not None and (evidence := outcome.evidence.get(member.key, "").strip()):
                parts.extend([t("report.evidence", locale), f"```\n{evidence}\n```"])
    else:
        if outcome is not None:
            reason = member_content[highest.key]
            evidence = outcome.evidence.get(highest.key, "")
            if reason:
                parts.append(t("report.reason", locale, p0=reason))
            if evidence:
                parts.extend([t("report.evidence", locale), f"```\n{evidence}\n```"])
        if representative.bodies:
            parts.append(representative.bodies[0])
    return "\n\n".join(parts)


@dataclass(frozen=True)
class _DisplayUnit:
    id: str
    keys: tuple[str, ...]
    priority: int
    pattern: PatternFold | None = None


def _folded_items(
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    included: set[str],
    *,
    locale: Locale = "en",
) -> list[str]:
    groups = {group.key: group for group in merged.groups}
    priority_index = {group.key: index for index, group in enumerate(merged.groups)}
    active_patterns = [
        fold for fold in merged.pattern_folds if all(key in included for key in fold.group_keys)
    ]
    pattern_by_key = {key: fold for fold in active_patterns for key in fold.group_keys}

    units: dict[str, _DisplayUnit] = {}
    for key in included:
        pattern = pattern_by_key.get(key)
        if pattern is None:
            units[f"group:{key}"] = _DisplayUnit(
                id=f"group:{key}", keys=(key,), priority=priority_index[key]
            )
            continue
        unit_id = f"pattern:{merged.pattern_folds.index(pattern)}"
        units.setdefault(
            unit_id,
            _DisplayUnit(
                id=unit_id,
                keys=tuple(pattern.group_keys),
                priority=min(priority_index[item] for item in pattern.group_keys),
                pattern=pattern,
            ),
        )

    unit_by_key = {key: unit.id for unit in units.values() for key in unit.keys}
    adjacency = {unit_id: set() for unit_id in units}
    for fold in merged.region_folds:
        region_units = list(
            dict.fromkeys(unit_by_key[key] for key in fold.group_keys if key in unit_by_key)
        )
        for left in region_units:
            adjacency[left].update(right for right in region_units if right != left)

    components: list[list[_DisplayUnit]] = []
    remaining = set(units)
    while remaining:
        root = min(remaining, key=lambda unit_id: units[unit_id].priority)
        stack = [root]
        remaining.remove(root)
        component: list[_DisplayUnit] = []
        while stack:
            unit_id = stack.pop()
            component.append(units[unit_id])
            for neighbor in sorted(adjacency[unit_id] & remaining):
                remaining.remove(neighbor)
                stack.append(neighbor)
        components.append(sorted(component, key=lambda unit: unit.priority))
    components.sort(key=lambda component: component[0].priority)

    labels_by_unit: dict[str, list[str]] = {unit_id: [] for unit_id in units}
    for fold in merged.region_folds:
        label = _region_label(fold, groups, locale=locale)
        for unit_id in dict.fromkeys(
            unit_by_key[key] for key in fold.group_keys if key in unit_by_key
        ):
            if label not in labels_by_unit[unit_id]:
                labels_by_unit[unit_id].append(label)

    rendered: list[str] = []
    for component in components:
        for unit in component:
            labels = labels_by_unit[unit.id]
            if unit.pattern is not None:
                rendered.append(
                    _render_pattern_item(
                        unit.pattern, groups, outcome, priority_index, labels, locale=locale
                    )
                )
            else:
                rendered.append(
                    render_group_item(
                        groups[unit.keys[0]], outcome, region_labels=labels, locale=locale
                    )
                )
    return rendered


def _confirmed_items(
    merged: MergeResult, outcome: AdjudicationOutcome, *, locale: Locale = "en"
) -> list[str]:
    confirmed = {
        group.key for group in merged.groups if outcome.verdicts.get(group.key) is Verdict.CONFIRMED
    }
    return _folded_items(merged, outcome, confirmed, locale=locale)


def _unadjudicated_items(merged: MergeResult, *, locale: Locale = "en") -> list[str]:
    return _folded_items(merged, None, {group.key for group in merged.groups}, locale=locale)


def _unresolved_items(
    merged: MergeResult, outcome: AdjudicationOutcome, *, locale: Locale = "en"
) -> list[str]:
    groups = {group.key: group for group in merged.groups}
    items: list[str] = []
    for key in outcome.unresolved:
        group = groups.get(key)
        if group is None:
            continue
        items.append(
            t("report.unresolved_note", locale, p0=render_group_item(group, outcome, locale=locale))
        )
    return items


def _rejected_items(
    merged: MergeResult, outcome: AdjudicationOutcome, *, locale: Locale = "en"
) -> list[str]:
    items: list[str] = []
    for group in merged.groups:
        if outcome.verdicts.get(group.key) is not Verdict.REJECTED:
            continue
        line = group.line if group.line is not None else t("common.unknown", locale)
        evidence = outcome.evidence.get(group.key, "")
        items.append(
            "\n".join(
                [
                    "<details>",
                    f"<summary>{group.rule_id} — {group.file}:{line}</summary>",
                    "",
                    t("report.finding_id", locale, p0=group.key),
                    "",
                    f"```\n{evidence}\n```",
                    "</details>",
                ]
            )
        )
    return items


def _coverage_section(
    coverage: Sequence[LaneCoverage],
    budget: DiffBudgetReport | None,
    outcome: AdjudicationOutcome | None,
    *,
    locale: Locale = "en",
) -> str:
    lines = [
        t("report.coverage_heading", locale),
        "",
        t("report.coverage_columns", locale),
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in coverage:
        lane_id = item.lane_id.replace("|", "\\|")
        lines.append(
            f"| {lane_id} | {item.dispatched} | {item.valid} | {item.findings} | "
            f"{len(item.uncovered)} |"
        )
    lines.append(
        t(
            "report.coverage_total",
            locale,
            p0=sum(item.dispatched for item in coverage),
            p1=sum(item.valid for item in coverage),
            p2=sum(item.findings for item in coverage),
            p3=sum(len(item.uncovered) for item in coverage),
        )
    )
    uncovered = [item for item in coverage if item.uncovered]
    if uncovered:
        lines.extend(["", t("report.uncovered", locale)])
        for item in uncovered:
            lane_id = item.lane_id.replace("`", "\\`")
            escaped_hunk_ids = [hunk_id.replace("`", "\\`") for hunk_id in item.uncovered]
            hunk_ids = ", ".join(f"`{hunk_id}`" for hunk_id in escaped_hunk_ids)
            lines.append(f"- `{lane_id}`: {hunk_ids}")
    if budget is not None:
        excluded = ", ".join(budget.excluded_files) or t("common.none", locale)
        lines.extend(
            [
                "",
                t(
                    "report.budget",
                    locale,
                    p0=budget.kept_chars,
                    p1=budget.excluded_chars,
                    p2=excluded,
                    p3=budget.chunk_count,
                ),
            ]
        )
    if outcome is not None and outcome.coerced_rejections > 0:
        lines.extend(["", t("report.coerced", locale, p0=outcome.coerced_rejections)])
    return "\n".join(lines)


def _status_section(summary: RunSummary | None, *, locale: Locale = "en") -> str:
    if summary is None:
        return ""
    if summary.status is ReviewStatus.DEGRADED:
        label = t("report.status.degraded", locale)
    elif summary.status is ReviewStatus.FAILED:
        label = t("report.status.failed", locale)
    elif summary.status is ReviewStatus.COMPLETE:
        label = t("report.status.complete", locale)
    else:
        label = t("report.status.running", locale)
    lines = [
        t("report.status_heading", locale),
        "",
        t("report.status", locale, p0=summary.status.value, p1=label),
    ]
    if summary.failed_lanes:
        lines.extend(["", t("report.failed_lanes", locale)])
        for lane in summary.failed_lanes:
            details = ", ".join(
                t("report.failure", locale, p0=failure.reason, p1=failure.replica, p2=failure.chunk)
                for failure in lane.failures
            )
            lines.append(f"- `{lane.lane_id}`: {details}")
    if summary.error is not None:
        lines.extend(
            [
                "",
                t(
                    "report.run_error",
                    locale,
                    p0=summary.error.stage,
                    p1=summary.error.reason,
                    p2=summary.error.message,
                ),
            ]
        )
    return "\n".join(lines)


def render_report(
    *,
    target: ResolvedTarget,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    coverage: Sequence[LaneCoverage],
    budget: DiffBudgetReport | None,
    synthesis: str | None = None,
    summary: RunSummary | None = None,
    locale: Locale = "en",
    presentation: PresentationConfig | None = None,
) -> str:
    """Render one report without reading or writing external state."""

    if presentation is not None:
        locale = presentation.locale
    display_name = presentation.display_name if presentation is not None else "rvw"
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [
        t(
            "report.header",
            locale,
            p0=target.repo,
            p1=_target_label(target, locale=locale),
            display_name=display_name,
        ),
        t("report.metadata", locale, p0=target.head_sha, p1=timestamp),
    ]
    status_section = _status_section(summary, locale=locale)
    if status_section:
        parts.append(status_section)
    parts.extend(
        [
            t("report.synthesis_heading", locale),
            synthesis if synthesis is not None else t("report.synthesis_placeholder", locale),
        ]
    )

    if outcome is None:
        items = _unadjudicated_items(merged, locale=locale)
        parts.extend(
            [
                t("report.unadjudicated_heading", locale),
                "\n\n".join(items) if items else t("report.empty", locale),
            ]
        )
    else:
        confirmed_items = _confirmed_items(merged, outcome, locale=locale)
        parts.extend(
            [
                t("report.confirmed_heading", locale),
                "\n\n".join(confirmed_items) if confirmed_items else t("report.empty", locale),
            ]
        )
        unresolved_items = _unresolved_items(merged, outcome, locale=locale)
        if unresolved_items:
            parts.extend([t("report.uncertain_heading", locale), "\n\n".join(unresolved_items)])
        rejected_items = _rejected_items(merged, outcome, locale=locale)
        if rejected_items:
            parts.extend([t("report.rejected_heading", locale), "\n\n".join(rejected_items)])

    build = summary.build if summary is not None else current_build_provenance()
    parts.extend(
        [
            _coverage_section(coverage, budget, outcome, locale=locale),
            t(
                "report.footer",
                locale,
                p0=__version__,
                p1=build.build_id,
                display_name=display_name,
            ),
        ]
    )
    return "\n\n".join(parts) + "\n"


__all__ = ["render_group_item", "render_report"]
