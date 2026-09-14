"""Deterministic finding collapse, site grouping, and display-only folds.

Pattern edges require same-rule groups in different files to have backtick-token
Jaccard similarity of at least 0.40.  The threshold is measured from the real
1119 fixture on backtick-only token sets: genuine pairs sit at 0.50-1.00 (the
catchtable retry pair is 0.50; the ``errorCodes`` component keeps all four
members connected through 0.50/0.667/1.00 edges even though its two weakest
pairs measure 0.333), while every incidental ``proxy_connect_failed`` link is
0.25-0.333.  0.40 separates the two edge populations with margin.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from rvw.discover import EnrichedFinding
from rvw.schema import EffectiveSeverity, FindingScope, ScopedFinding, Severity, Tier

_BACKTICK_TOKEN = re.compile(r"`([^`\n]+)`")
_PATTERN_JACCARD_THRESHOLD = 0.40
_SEVERITY_PRIORITY = {
    Severity.SUGGESTION: 1,
    Severity.WARNING: 2,
    Severity.BLOCKER: 3,
}
_EFFECTIVE_PRIORITY = {
    severity: rank
    for rank, severity in enumerate(
        (
            EffectiveSeverity.INFO,
            EffectiveSeverity.SUGGESTION,
            EffectiveSeverity.WARNING,
            EffectiveSeverity.BLOCKER,
        )
    )
}
_SCOPE_PRIORITY = {
    FindingScope.OUTSIDE_DIFF: 0,
    FindingScope.UNCHANGED_IN_FILE: 1,
    FindingScope.CHANGED: 2,
}


class CollapseGroup(ScopedFinding):
    """One ADR-003 adjudication unit collapsed across lane replicas.

    ``priority`` stores the four descending numeric priority axes in order:
    cross-layer, agreement, pattern repetition, and severity. Deterministic
    file/line/hunk/rule tie-breakers are applied when ``MergeResult.groups`` is
    sorted, but are not encoded in the reusable numeric axes.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    rule_id: str
    file: str
    hunk_id: str
    line: int | None
    severity: Severity
    lane_ids: list[str]
    agreement: int
    bodies: list[str]
    anchorable: bool
    findings: list[EnrichedFinding]
    priority: list[int] = Field(min_length=4, max_length=4)


class Site(BaseModel):
    """Collapse groups sharing one diff hunk."""

    model_config = ConfigDict(extra="forbid")

    file: str
    hunk_id: str
    group_keys: list[str]
    lanes: list[str]
    corroboration: int
    cross_layer: bool


class PatternFold(BaseModel):
    """Same-rule groups connected across files by backtick identifiers.

    ``shared_identifiers`` is the token intersection across the full component.
    When that is empty despite pairwise graph links, it is the sorted union of
    tokens shared by the component's individual edges.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    group_keys: list[str] = Field(min_length=2)
    shared_identifiers: list[str]
    repetition: int = Field(ge=2)


class RegionFold(BaseModel):
    """Line-bounded groups connected within one file."""

    model_config = ConfigDict(extra="forbid")

    file: str
    group_keys: list[str] = Field(min_length=2)
    lanes: list[str]


class MergeResult(BaseModel):
    """Complete deterministic output of the MERGE stage."""

    model_config = ConfigDict(extra="forbid")

    groups: list[CollapseGroup]
    sites: list[Site]
    pattern_folds: list[PatternFold]
    region_folds: list[RegionFold]


def _collapse_key(file: str, hunk_id: str, rule_id: str) -> str:
    identity = f"{file}:{hunk_id}:{rule_id}".encode()
    return hashlib.sha1(identity).hexdigest()


def _collapse(findings: Sequence[EnrichedFinding]) -> list[CollapseGroup]:
    members: dict[tuple[str, str, str], list[EnrichedFinding]] = {}
    for finding in findings:
        identity = (finding.file, finding.hunk_id, finding.rule_id)
        members.setdefault(identity, []).append(finding)

    groups: list[CollapseGroup] = []
    for (file, hunk_id, rule_id), grouped_findings in members.items():
        bodies = list(dict.fromkeys(finding.body for finding in grouped_findings))
        severity = max(
            (finding.severity for finding in grouped_findings),
            key=_SEVERITY_PRIORITY.__getitem__,
        )
        groups.append(
            CollapseGroup(
                key=_collapse_key(file, hunk_id, rule_id),
                rule_id=rule_id,
                file=file,
                hunk_id=hunk_id,
                line=grouped_findings[0].line,
                severity=severity,
                scope=max(
                    (finding.scope for finding in grouped_findings),
                    key=_SCOPE_PRIORITY.__getitem__,
                ),
                lane_ids=sorted({finding.lane_id for finding in grouped_findings}),
                agreement=len({finding.replica for finding in grouped_findings}),
                bodies=bodies,
                anchorable=any(finding.anchorable for finding in grouped_findings),
                findings=list(grouped_findings),
                priority=[0, 0, 0, 0],
            )
        )
    return groups


def _sites(
    groups: Sequence[CollapseGroup], lane_tiers: Mapping[str, Tier]
) -> tuple[list[Site], dict[str, bool]]:
    grouped: dict[tuple[str, str], list[CollapseGroup]] = defaultdict(list)
    for group in groups:
        grouped[(group.file, group.hunk_id)].append(group)

    sites: list[Site] = []
    cross_layer_by_group: dict[str, bool] = {}
    for (file, hunk_id), site_groups in sorted(grouped.items()):
        lanes = sorted({lane for group in site_groups for lane in group.lane_ids})
        tiers = {lane_tiers[lane] for lane in lanes}
        cross_layer = len(tiers) > 1
        group_keys = sorted(group.key for group in site_groups)
        sites.append(
            Site(
                file=file,
                hunk_id=hunk_id,
                group_keys=group_keys,
                lanes=lanes,
                corroboration=len(lanes),
                cross_layer=cross_layer,
            )
        )
        cross_layer_by_group.update(dict.fromkeys(group_keys, cross_layer))
    return sites, cross_layer_by_group


def _tokens(group: CollapseGroup) -> set[str]:
    return {token for body in group.bodies for token in _BACKTICK_TOKEN.findall(body)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _components(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[list[str]]:
    adjacent: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        adjacent[left].add(right)
        adjacent[right].add(left)

    components: list[list[str]] = []
    remaining = set(nodes)
    while remaining:
        root = min(remaining)
        stack = [root]
        component: list[str] = []
        remaining.remove(root)
        while stack:
            node = stack.pop()
            component.append(node)
            neighbors = sorted(adjacent[node] & remaining, reverse=True)
            for neighbor in neighbors:
                remaining.remove(neighbor)
                stack.append(neighbor)
        components.append(sorted(component))
    return components


def _distinct_file_components(
    groups: Sequence[CollapseGroup], edges: Sequence[tuple[str, str]]
) -> list[list[str]]:
    """Build deterministic linked components without repeating a file in one fold."""

    parent = {group.key: group.key for group in groups}
    component_files = {group.key: {group.file} for group in groups}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for left, right in sorted(edges):
        left_root = root(left)
        right_root = root(right)
        if left_root == right_root or component_files[left_root] & component_files[right_root]:
            continue
        retained, merged = sorted((left_root, right_root))
        parent[merged] = retained
        component_files[retained].update(component_files.pop(merged))

    linked_keys = {key for edge in edges for key in edge}
    components: dict[str, list[str]] = defaultdict(list)
    for key in sorted(linked_keys):
        components[root(key)].append(key)
    return [component for component in components.values() if len(component) >= 2]


def _pattern_folds(groups: Sequence[CollapseGroup]) -> list[PatternFold]:
    by_rule: dict[str, list[CollapseGroup]] = defaultdict(list)
    for group in groups:
        by_rule[group.rule_id].append(group)

    folds: list[PatternFold] = []
    for rule_id, rule_groups in sorted(by_rule.items()):
        ordered = sorted(rule_groups, key=lambda group: (group.file, group.key))
        by_key = {group.key: group for group in ordered}
        tokens = {group.key: _tokens(group) for group in ordered}
        edges: list[tuple[str, str]] = []
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if (
                    left.file != right.file
                    and _jaccard(tokens[left.key], tokens[right.key]) >= _PATTERN_JACCARD_THRESHOLD
                ):
                    edges.append((left.key, right.key))

        for component in _distinct_file_components(ordered, edges):
            component_groups = [by_key[group_key] for group_key in component]
            if len(component_groups) < 2:
                continue
            shared = set.intersection(*(tokens[group.key] for group in component_groups))
            if not shared:
                shared = set()
                component_keys = set(component)
                for left, right in edges:
                    if left in component_keys and right in component_keys:
                        shared.update(tokens[left] & tokens[right])
            group_keys = [group.key for group in component_groups]
            folds.append(
                PatternFold(
                    rule_id=rule_id,
                    group_keys=group_keys,
                    shared_identifiers=sorted(shared),
                    repetition=len(group_keys),
                )
            )
    return folds


def _region_folds(groups: Sequence[CollapseGroup]) -> list[RegionFold]:
    by_file: dict[str, list[CollapseGroup]] = defaultdict(list)
    for group in groups:
        if group.line is not None:
            by_file[group.file].append(group)

    folds: list[RegionFold] = []
    for file, file_groups in sorted(by_file.items()):
        ordered = sorted(file_groups, key=lambda group: (group.line or 0, group.key))
        edges: list[tuple[str, str]] = []
        for left, right in pairwise(ordered):
            if left.line is not None and right.line is not None and right.line - left.line <= 15:
                edges.append((left.key, right.key))
        linked_keys = {key for edge in edges for key in edge}
        by_key = {group.key: group for group in ordered}
        for component in _components(sorted(linked_keys), edges):
            component_groups = sorted(
                (by_key[group_key] for group_key in component),
                key=lambda group: (group.line or 0, group.key),
            )
            if len(component_groups) < 2:
                continue
            folds.append(
                RegionFold(
                    file=file,
                    group_keys=[group.key for group in component_groups],
                    lanes=sorted({lane for group in component_groups for lane in group.lane_ids}),
                )
            )
    return folds


def merge(findings: Sequence[EnrichedFinding], *, lane_tiers: Mapping[str, Tier]) -> MergeResult:
    """Collapse findings and independently compute site, pattern, and region views.

    Pattern and region edges are built from raw collapse groups and are never
    combined. A group can consequently appear in both display layers without
    allowing transitive connectivity to cross from one layer into the other.
    """

    groups = _collapse(findings)
    sites, cross_layer_by_group = _sites(groups, lane_tiers)
    pattern_folds = _pattern_folds(groups)
    region_folds = _region_folds(groups)
    repetition_by_group = {
        group_key: fold.repetition for fold in pattern_folds for group_key in fold.group_keys
    }

    for group in groups:
        group.priority = [
            int(cross_layer_by_group[group.key]),
            group.agreement,
            repetition_by_group.get(group.key, 1),
            _EFFECTIVE_PRIORITY[group.effective_severity],
        ]
    groups.sort(
        key=lambda group: (
            *(-axis for axis in group.priority),
            group.file,
            group.line is None,
            group.line if group.line is not None else 0,
            group.hunk_id,
            group.rule_id,
            group.key,
        )
    )
    return MergeResult(
        groups=groups,
        sites=sites,
        pattern_folds=pattern_folds,
        region_folds=region_folds,
    )


__all__ = [
    "CollapseGroup",
    "MergeResult",
    "PatternFold",
    "RegionFold",
    "Site",
    "merge",
]
