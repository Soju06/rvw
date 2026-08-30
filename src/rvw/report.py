"""Deterministic machine-rendered Korean review reports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from rvw import __version__
from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport
from rvw.discover import LaneCoverage
from rvw.merge import CollapseGroup, MergeResult, PatternFold, RegionFold
from rvw.provenance import current_build_provenance
from rvw.schema import Verdict
from rvw.summary import ReviewStatus, RunSummary
from rvw.target import ResolvedTarget

_SYNTHESIS_PLACEHOLDER = "_(종합은 오케스트레이터가 작성합니다 — rvw report --synthesis 로 주입)_"


def _target_label(target: ResolvedTarget) -> str:
    if target.kind == "pr":
        return f"PR#{target.pr_number}"
    if target.kind == "commit":
        return f"commit {target.head_sha[:9]}"
    return "uncommitted"


def _region_label(fold: RegionFold, groups: dict[str, CollapseGroup]) -> str:
    lines = [line for key in fold.group_keys if (line := groups[key].line) is not None]
    return f"(인접: {fold.file} L{min(lines)}\N{EN DASH}{max(lines)})"


def _votes(outcome: AdjudicationOutcome | None, key: str) -> str:
    if outcome is None:
        return "미판정"
    return "/".join(verdict.value for verdict in outcome.replica_votes.get(key, [])) or "없음"


def render_group_item(
    group: CollapseGroup,
    outcome: AdjudicationOutcome | None,
    *,
    region_labels: Sequence[str] = (),
) -> str:
    """Render one non-folded finding item for reports and inline publication."""

    line = group.line if group.line is not None else "unknown"
    suffix = "" if not region_labels else f" {' '.join(region_labels)}"
    parts = [
        f"### [{group.severity.value}] {group.rule_id} — {group.file}:{line}{suffix}",
        f"Finding ID: `{group.key}`",
        f"복제 동의 {group.agreement}/3 · 판정 {_votes(outcome, group.key)}",
    ]
    if outcome is not None:
        reason = outcome.reasons.get(group.key, "")
        evidence = outcome.evidence.get(group.key, "")
        if reason:
            parts.append(f"판정 사유: {reason}")
        if evidence:
            parts.extend(["근거:", f"```\n{evidence}\n```"])
    if group.bodies:
        parts.append(group.bodies[0])
    return "\n\n".join(parts)


def _render_pattern_item(
    fold: PatternFold,
    groups: dict[str, CollapseGroup],
    outcome: AdjudicationOutcome | None,
    priority_index: dict[str, int],
    region_labels: Sequence[str],
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
    parts = [f"### {fold.rule_id} — {fold.repetition}개 위치 (반복 패턴){suffix}"]
    parts.extend(
        (
            f"- `{member.file}:{member.line if member.line is not None else 'unknown'}` "
            f"— Finding ID: `{member.key}`"
        )
        for member in members
    )
    if fold.shared_identifiers:
        identifiers = ", ".join(f"`{identifier}`" for identifier in fold.shared_identifiers)
        parts.append(f"공유 식별자: {identifiers}")
    parts.append(f"복제 동의 {highest.agreement}/3 · 판정 {_votes(outcome, highest.key)}")

    if differing_content:
        for member in members:
            line = member.line if member.line is not None else "unknown"
            parts.append(f"**{member.file}:{line}** — {member_content[member.key]}")
            if outcome is not None and (evidence := outcome.evidence.get(member.key, "").strip()):
                parts.extend(["근거:", f"```\n{evidence}\n```"])
    else:
        if outcome is not None:
            reason = member_content[highest.key]
            evidence = outcome.evidence.get(highest.key, "")
            if reason:
                parts.append(f"판정 사유: {reason}")
            if evidence:
                parts.extend(["근거:", f"```\n{evidence}\n```"])
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
        label = _region_label(fold, groups)
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
                    _render_pattern_item(unit.pattern, groups, outcome, priority_index, labels)
                )
            else:
                rendered.append(
                    render_group_item(groups[unit.keys[0]], outcome, region_labels=labels)
                )
    return rendered


def _confirmed_items(merged: MergeResult, outcome: AdjudicationOutcome) -> list[str]:
    confirmed = {
        group.key for group in merged.groups if outcome.verdicts.get(group.key) is Verdict.CONFIRMED
    }
    return _folded_items(merged, outcome, confirmed)


def _unadjudicated_items(merged: MergeResult) -> list[str]:
    return _folded_items(merged, None, {group.key for group in merged.groups})


def _unresolved_items(merged: MergeResult, outcome: AdjudicationOutcome) -> list[str]:
    groups = {group.key: group for group in merged.groups}
    items: list[str] = []
    for key in outcome.unresolved:
        group = groups.get(key)
        if group is None:
            continue
        items.append(
            f"{render_group_item(group, outcome)}\n\n"
            "확장 컨텍스트 재검증에서도 미확정 — 수동 확인 필요"
        )
    return items


def _rejected_items(merged: MergeResult, outcome: AdjudicationOutcome) -> list[str]:
    items: list[str] = []
    for group in merged.groups:
        if outcome.verdicts.get(group.key) is not Verdict.REJECTED:
            continue
        line = group.line if group.line is not None else "unknown"
        evidence = outcome.evidence.get(group.key, "")
        items.append(
            "\n".join(
                [
                    "<details>",
                    f"<summary>{group.rule_id} — {group.file}:{line}</summary>",
                    "",
                    f"Finding ID: `{group.key}`",
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
) -> str:
    lines = [
        "## 커버리지",
        "",
        "| 레인 | 상태 | 발사 | 유효 | 발견 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for item in coverage:
        lane_id = item.lane_id.replace("|", "\\|")
        if item.skipped_reason is not None:
            status = f"skipped: {item.skipped_reason}"
        elif item.valid == item.dispatched:
            status = "complete"
        elif item.valid == 0:
            status = "failed"
        else:
            status = "degraded"
        lines.append(
            f"| {lane_id} | {status} | {item.dispatched} | {item.valid} | {item.findings} |"
        )
    lines.append(
        "| 합계 | - | "
        f"{sum(item.dispatched for item in coverage)} | "
        f"{sum(item.valid for item in coverage)} | "
        f"{sum(item.findings for item in coverage)} |"
    )
    if budget is not None:
        excluded = ", ".join(budget.excluded_files) or "없음"
        lines.extend(
            [
                "",
                f"diff 예산: {budget.kept_chars:,}자 유지 / {budget.excluded_chars:,}자 제외 "
                f"({excluded}) / {budget.chunk_count}청크",
            ]
        )
    if outcome is not None and outcome.coerced_rejections > 0:
        lines.extend(["", f"근거 없는 기각 교정: {outcome.coerced_rejections}건"])
    return "\n".join(lines)


def _status_section(summary: RunSummary | None) -> str:
    if summary is None:
        return ""
    if summary.status is ReviewStatus.DEGRADED:
        label = "partial review — one or more lane executions failed"
    elif summary.status is ReviewStatus.FAILED:
        label = "failed review — results are incomplete"
    elif summary.status is ReviewStatus.COMPLETE:
        label = "complete review"
    else:
        label = "review still running"
    lines = ["## 실행 상태", "", f"status: `{summary.status.value}` — {label}"]
    if summary.failed_lanes:
        lines.extend(["", "failed lanes:"])
        for lane in summary.failed_lanes:
            details = ", ".join(
                f"`{failure.reason}` (replica {failure.replica}, chunk {failure.chunk})"
                for failure in lane.failures
            )
            lines.append(f"- `{lane.lane_id}`: {details}")
    if summary.skipped_lanes:
        lines.extend(["", "skipped lanes (incomplete coverage):"])
        for lane in summary.skipped_lanes:
            lines.append(f"- `{lane.lane_id}`: `{lane.reason}`")
    if summary.error is not None:
        lines.extend(
            [
                "",
                f"run error: `{summary.error.stage}/{summary.error.reason}` — "
                f"{summary.error.message}",
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
) -> str:
    """Render one report without reading or writing external state."""

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [
        f"# rvw 리뷰 — {target.repo} {_target_label(target)}",
        f"head: `{target.head_sha}`  \nUTC timestamp: {timestamp}",
    ]
    status_section = _status_section(summary)
    if status_section:
        parts.append(status_section)
    parts.extend(["## 종합", synthesis if synthesis is not None else _SYNTHESIS_PLACEHOLDER])

    if outcome is None:
        items = _unadjudicated_items(merged)
        parts.extend(["## 발견 (미판정)", "\n\n".join(items) if items else "_없음_"])
    else:
        confirmed_items = _confirmed_items(merged, outcome)
        parts.extend(
            [
                "## 확정 발견 (CONFIRMED)",
                "\n\n".join(confirmed_items) if confirmed_items else "_없음_",
            ]
        )
        unresolved_items = _unresolved_items(merged, outcome)
        if unresolved_items:
            parts.extend(["## 검증 미확정", "\n\n".join(unresolved_items)])
        rejected_items = _rejected_items(merged, outcome)
        if rejected_items:
            parts.extend(["## 기각 (REJECTED)", "\n\n".join(rejected_items)])

    build = summary.build if summary is not None else current_build_provenance()
    parts.extend(
        [
            _coverage_section(coverage, budget, outcome),
            f"_generated by rvw {__version__} · build {build.build_id}_",
        ]
    )
    return "\n\n".join(parts) + "\n"


__all__ = ["render_group_item", "render_report"]
