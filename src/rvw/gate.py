"""Fail-closed PR gate models, validation, checkout, and verdict rendering."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rvw.adjudicate import AdjudicationOutcome
from rvw.checkout import provision_checkout
from rvw.discover import LaneCoverage
from rvw.hunks import hunk_sha256_by_id
from rvw.i18n import Locale, t
from rvw.merge import CollapseGroup, MergeResult
from rvw.presentation import PresentationConfig
from rvw.schema import Severity, Verdict
from rvw.target import ResolvedTarget

ACTIONABLE_DISPOSITIONS_PAUSE = "actionable findings require explicit dispositions"


class GateInvariantError(ValueError):
    """Persisted review data does not satisfy the fail-closed gate contract."""


class GitHubAuthorizationError(RuntimeError):
    """Operational failure while resolving blocker-acceptance authority."""

    def __init__(self, *, step: str, actor: str | None, detail: str) -> None:
        self.step = step
        self.actor = actor
        self.detail = detail
        super().__init__(detail)


class GateAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_sha: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")


class PullRequestState(GateAnchor):
    state: str
    merged: bool


class GatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    lane_ids: list[str] = Field(min_length=1)
    replicas: int = Field(ge=1)
    adjudicate_replicas: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    discovery_mode: Literal["agentic", "inline"] = "inline"

    @model_validator(mode="before")
    @classmethod
    def _legacy_adjudicate_replicas(cls, value: object) -> object:
        """Plans persisted before the replica split ran one combined count.

        For such plans the historical adjudication count IS the stored
        ``replicas`` value; backfilling the new-default 3 would fabricate
        provenance for runs that adjudicated with 1.
        """

        if isinstance(value, Mapping) and "adjudicate_replicas" not in value:
            inferred = dict(value)
            inferred["adjudicate_replicas"] = inferred.get("replicas")
            return inferred
        return value

    @field_validator("lane_ids")
    @classmethod
    def _lanes_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError(t("gate.error.gate_plan_lane_IDs_must", "en"))
        return value


class DispositionDecision(StrEnum):
    ACCEPTED = "accepted"
    MUST_FIX = "must_fix"


class DispositionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    decision: DispositionDecision
    reason: str
    inherited_from: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_must_be_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(t("gate.error.disposition_reason_must_be_nonblank", "en"))
        return value.strip()


class DispositionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    dispositions: list[DispositionRecord]


class InheritanceTier(StrEnum):
    EXACT_ID = "exact_id"
    UNIQUE_PAIR = "unique_pair"
    UNIQUE_PAIR_STICKY = "unique_pair_sticky"


class InheritanceBlankReason(StrEnum):
    UNMATCHED = "unmatched"
    PRIOR_MUST_FIX = "prior_must_fix"
    SOURCE_PAIR_AMBIGUOUS = "source_pair_ambiguous"
    CURRENT_PAIR_AMBIGUOUS = "current_pair_ambiguous"
    CONTENT_CHANGED = "content_changed"
    SOURCE_DIGEST_MISSING = "source_digest_missing"
    CURRENT_DIGEST_MISSING = "current_digest_missing"
    DIAGNOSIS_CHANGED = "diagnosis_changed"
    FINDING_ID_CHANGED = "finding_id_changed"
    SEVERITY_CHANGED = "severity_changed"
    IDENTITY_MISMATCH = "identity_mismatch"


class GateFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    rule_id: str
    file: str
    line: int | None
    severity: Severity
    verdict: Verdict
    disposition: DispositionDecision
    reason: str
    inherited_from: str | None = None
    hunk_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    body_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    inheritance_tier: InheritanceTier | None = None
    inheritance_blank_reason: InheritanceBlankReason | None = None


class DispositionInheritance(BaseModel):
    """Generated inheritance state for one current actionable finding."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    decision: DispositionDecision = DispositionDecision.MUST_FIX
    reason: str = ""
    inherited_from: str | None = None
    tier: InheritanceTier | None = None
    blank_reason: InheritanceBlankReason | None = None


class InheritanceSummary(BaseModel):
    """Aggregate outcomes for one selected inheritance source."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str
    carried: int = Field(ge=0)
    sticky: int = Field(default=0, ge=0)
    prefilled: int = Field(ge=0)
    blank: int = Field(ge=0)
    reasons: dict[InheritanceBlankReason, int] = Field(default_factory=dict)


class GateVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    repo: str
    pr_number: int
    anchor: GateAnchor
    counts: dict[str, int]
    coverage: list[LaneCoverage]
    findings: list[GateFinding]
    actor: str | None = None
    verdict: Literal["PASS", "BLOCK"]
    kind: Literal["pause", "failure", "completed"] = "failure"
    failures: list[str] = Field(default_factory=list)
    inheritance_summary: InheritanceSummary | None = None

    @model_validator(mode="before")
    @classmethod
    def _infer_legacy_kind(cls, value: object) -> object:
        if not isinstance(value, Mapping) or "kind" in value:
            return value
        inferred = dict(value)
        failures = inferred.get("failures")
        findings = inferred.get("findings")
        if isinstance(failures, list) and ACTIONABLE_DISPOSITIONS_PAUSE in failures:
            inferred["kind"] = "pause"
        elif isinstance(findings, list) and findings:
            inferred["kind"] = "completed"
        else:
            inferred["kind"] = "failure"
        return inferred


def load_dispositions(path: Path) -> DispositionDocument:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            t("gate.error.could_not_load_dispositions_from", "en", p0=path, p1=exc)
        ) from exc
    return DispositionDocument.model_validate(raw)


def save_gate_plan(run_dir: Path, plan: GatePlan) -> Path:
    path = run_dir / "gate-plan.json"
    path.write_text(
        f"{json.dumps(plan.model_dump(mode='json'), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return path


def load_gate_plan(run_dir: Path) -> GatePlan:
    path = run_dir / "gate-plan.json"
    return GatePlan.model_validate_json(path.read_text(encoding="utf-8"))


def validate_coverage(
    planned_lane_ids: Sequence[str],
    coverage: Sequence[LaneCoverage],
    *,
    replicas: int,
    chunk_count: int,
) -> list[LaneCoverage]:
    if replicas < 1:
        raise GateInvariantError(t("gate.error.expected_replicas_must_be_positive", "en"))
    if chunk_count < 1:
        raise GateInvariantError(t("gate.error.expected_chunk_count_must_be_positive", "en"))
    if not coverage:
        raise GateInvariantError(t("gate.error.coverage_must_be_nonempty", "en"))

    coverage_ids = [item.lane_id for item in coverage]
    duplicates = sorted(lane_id for lane_id, count in Counter(coverage_ids).items() if count > 1)
    if duplicates:
        raise GateInvariantError(
            t("gate.error.duplicate_coverage_lanes", "en", p0=", ".join(duplicates))
        )

    planned = set(planned_lane_ids)
    actual = set(coverage_ids)
    missing = sorted(planned - actual)
    unexpected = sorted(actual - planned)
    if not planned:
        detail = (
            t("gate.error.unexpected_coverage_lanes", "en", p0=", ".join(unexpected))
            if unexpected
            else ""
        )
        raise GateInvariantError(t("gate.error.planned_lane_set_must_be", "en", p0=detail))
    if missing:
        raise GateInvariantError(
            t("gate.error.missing_planned_coverage_lanes", "en", p0=", ".join(missing))
        )
    if unexpected:
        raise GateInvariantError(
            t("gate.error.unexpected_coverage_lanes_10", "en", p0=", ".join(unexpected))
        )

    by_lane = {item.lane_id: item for item in coverage}
    ordered: list[LaneCoverage] = []
    expected_runs = {
        (replica, chunk)
        for chunk in range(1, chunk_count + 1)
        for replica in range(1, replicas + 1)
    }
    for lane_id in planned_lane_ids:
        item = by_lane[lane_id]
        if item.dispatched <= 0:
            raise GateInvariantError(t("gate.error.lane", "en", p0=lane_id, p1=item.dispatched))
        actual_runs = {(run.replica, run.chunk) for run in item.runs}
        missing_runs = sorted(expected_runs - actual_runs, key=lambda value: (value[1], value[0]))
        unexpected_runs = sorted(
            actual_runs - expected_runs, key=lambda value: (value[1], value[0])
        )
        if missing_runs:
            detail = ", ".join(
                t("gate.error.replica", "en", p0=replica, p1=chunk)
                for replica, chunk in missing_runs
            )
            raise GateInvariantError(t("gate.error.lane_13", "en", p0=lane_id, p1=detail))
        if unexpected_runs:
            detail = ", ".join(
                t("gate.error.replica", "en", p0=replica, p1=chunk)
                for replica, chunk in unexpected_runs
            )
            raise GateInvariantError(t("gate.error.lane_14", "en", p0=lane_id, p1=detail))
        expected_count = replicas * chunk_count
        if item.dispatched != expected_count:
            raise GateInvariantError(
                t("gate.error.lane_15", "en", p0=lane_id, p1=item.dispatched, p2=expected_count)
            )
        invalid_runs = [run for run in item.runs if not run.valid]
        if invalid_runs:
            run = invalid_runs[0]
            raise GateInvariantError(
                t(
                    "gate.error.lane_16",
                    "en",
                    p0=lane_id,
                    p1=run.replica,
                    p2=run.chunk,
                    p3=run.invalid_reason,
                )
            )
        ordered.append(item)
    return ordered


def _actionable(
    merged: MergeResult, outcome: AdjudicationOutcome
) -> list[tuple[CollapseGroup, Verdict]]:
    merged_keys = {group.key for group in merged.groups}
    outcome_keys = set(outcome.verdicts)
    if outcome_keys != merged_keys:
        missing = sorted(merged_keys - outcome_keys)
        orphan = sorted(outcome_keys - merged_keys)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if orphan:
            details.append(f"orphan={','.join(orphan)}")
        raise GateInvariantError(
            t("gate.error.adjudication_outcome_keys_must_exactly", "en") + "; ".join(details)
        )
    actionable: list[tuple[CollapseGroup, Verdict]] = []
    for group in merged.groups:
        verdict = outcome.verdicts.get(group.key)
        if verdict is None:
            raise GateInvariantError(
                t("gate.error.missing_adjudication_verdict_for_finding", "en", p0=group.key)
            )
        if verdict in {Verdict.CONFIRMED, Verdict.UNCERTAIN}:
            actionable.append((group, verdict))
    return actionable


def _dispositions_by_id(
    document: DispositionDocument, expected_ids: set[str]
) -> dict[str, DispositionRecord]:
    ids = [record.finding_id for record in document.dispositions]
    duplicates = sorted(finding_id for finding_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise GateInvariantError(
            t("gate.error.duplicate_disposition_finding_IDs", "en", p0=", ".join(duplicates))
        )
    actual_ids = set(ids)
    unknown = sorted(actual_ids - expected_ids)
    if unknown:
        raise GateInvariantError(
            t("gate.error.unknown_disposition_finding_IDs", "en", p0=", ".join(unknown))
        )
    missing = sorted(expected_ids - actual_ids)
    if missing:
        raise GateInvariantError(
            t("gate.error.missing_disposition_finding_IDs", "en", p0=", ".join(missing))
        )
    return {record.finding_id: record for record in document.dispositions}


def _body_sha256(group: CollapseGroup) -> str:
    """Digest the complete order-insensitive body set for a collapsed finding."""

    if not group.bodies:
        raise GateInvariantError(t("gate.error.collapsed_finding", "en", p0=group.key))
    body_digests = (hashlib.sha256(body.encode()).digest() for body in sorted(group.bodies))
    return hashlib.sha256(b"".join(body_digests)).hexdigest()


def match_inherited_dispositions(
    inherited_findings: Sequence[GateFinding],
    merged: MergeResult,
    outcome: AdjudicationOutcome,
    *,
    inherited_run_id: str,
    current_hunk_sha256: Mapping[str, str | None] | None = None,
) -> dict[str, DispositionInheritance]:
    """Match validated prior findings to the current actionable finding set."""

    actionable = [group for group, _ in _actionable(merged, outcome)]
    current_digests = current_hunk_sha256 or {}
    results: dict[str, DispositionInheritance] = {}
    accepted_by_id = {
        finding.finding_id: finding
        for finding in inherited_findings
        if finding.disposition is DispositionDecision.ACCEPTED
    }
    inherited_pair_counts = Counter(
        (finding.file, finding.rule_id) for finding in inherited_findings
    )
    current_pair_counts = Counter((group.file, group.rule_id) for group in actionable)
    inherited_by_pair = {
        (finding.file, finding.rule_id): finding
        for finding in inherited_findings
        if finding.disposition is DispositionDecision.ACCEPTED
    }

    for group in actionable:
        current_body_digest = _body_sha256(group)
        pair = (group.file, group.rule_id)
        if inherited_pair_counts[pair] > 1:
            results[group.key] = DispositionInheritance(
                finding_id=group.key,
                blank_reason=InheritanceBlankReason.SOURCE_PAIR_AMBIGUOUS,
            )
            continue
        if current_pair_counts[pair] > 1:
            results[group.key] = DispositionInheritance(
                finding_id=group.key,
                blank_reason=InheritanceBlankReason.CURRENT_PAIR_AMBIGUOUS,
            )
            continue

        exact = accepted_by_id.get(group.key)
        demotion_reason: InheritanceBlankReason | None = None
        if exact is not None:
            if (exact.file, exact.rule_id) != pair:
                results[group.key] = DispositionInheritance(
                    finding_id=group.key,
                    blank_reason=InheritanceBlankReason.IDENTITY_MISMATCH,
                )
                continue
            inherited_digest = exact.hunk_sha256
            current_digest = current_digests.get(group.key)
            inherited_body_digest = exact.body_sha256
            if exact.severity is not group.severity:
                demotion_reason = InheritanceBlankReason.SEVERITY_CHANGED
            elif (
                inherited_digest is not None
                and current_digest is not None
                and inherited_digest == current_digest
                and inherited_body_digest is not None
                and inherited_body_digest == current_body_digest
            ):
                results[group.key] = DispositionInheritance(
                    finding_id=group.key,
                    decision=DispositionDecision.ACCEPTED,
                    reason=exact.reason,
                    inherited_from=inherited_run_id,
                    tier=InheritanceTier.EXACT_ID,
                )
                continue
            if demotion_reason is None:
                if inherited_digest is None or inherited_body_digest is None:
                    demotion_reason = InheritanceBlankReason.SOURCE_DIGEST_MISSING
                elif current_digest is None:
                    demotion_reason = InheritanceBlankReason.CURRENT_DIGEST_MISSING
                elif inherited_digest != current_digest:
                    demotion_reason = InheritanceBlankReason.CONTENT_CHANGED
                else:
                    demotion_reason = InheritanceBlankReason.DIAGNOSIS_CHANGED

        inherited = inherited_by_pair.get(pair)
        if inherited is None:
            blank_reason = (
                InheritanceBlankReason.PRIOR_MUST_FIX
                if inherited_pair_counts[pair] == 1
                else InheritanceBlankReason.UNMATCHED
            )
            results[group.key] = DispositionInheritance(
                finding_id=group.key,
                blank_reason=blank_reason,
            )
            continue
        if inherited.severity is not group.severity:
            demotion_reason = InheritanceBlankReason.SEVERITY_CHANGED
        sticky = inherited.severity is group.severity and group.severity is not Severity.BLOCKER
        results[group.key] = DispositionInheritance(
            finding_id=group.key,
            decision=(DispositionDecision.ACCEPTED if sticky else DispositionDecision.MUST_FIX),
            reason=inherited.reason,
            inherited_from=inherited_run_id,
            tier=(InheritanceTier.UNIQUE_PAIR_STICKY if sticky else InheritanceTier.UNIQUE_PAIR),
            blank_reason=demotion_reason or InheritanceBlankReason.FINDING_ID_CHANGED,
        )
    return results


def summarize_inheritance(
    inheritance: Mapping[str, DispositionInheritance],
    *,
    source_run_id: str,
) -> InheritanceSummary:
    carried = 0
    sticky = 0
    prefilled = 0
    blank = 0
    reasons: Counter[InheritanceBlankReason] = Counter()
    for result in inheritance.values():
        if result.tier is InheritanceTier.EXACT_ID:
            carried += 1
        elif result.tier is InheritanceTier.UNIQUE_PAIR_STICKY:
            sticky += 1
        elif result.reason:
            prefilled += 1
        else:
            blank += 1
        if result.blank_reason is not None:
            reasons[result.blank_reason] += 1
    return InheritanceSummary(
        source_run_id=source_run_id,
        carried=carried,
        sticky=sticky,
        prefilled=prefilled,
        blank=blank,
        reasons=dict(sorted(reasons.items(), key=lambda item: item[0].value)),
    )


def _validate_inherited_from(
    dispositions: Mapping[str, DispositionRecord],
    *,
    inherited_run_id: str | None,
    inheritance: Mapping[str, DispositionInheritance] | None,
) -> None:
    for finding_id, record in dispositions.items():
        if record.inherited_from is None:
            continue
        matched = inheritance.get(finding_id) if inheritance is not None else None
        if (
            inherited_run_id is None
            or record.inherited_from != inherited_run_id
            or matched is None
            or matched.tier is None
            or matched.inherited_from != inherited_run_id
        ):
            raise GateInvariantError(
                t(
                    "gate.error.inherited_from_unbound",
                    "en",
                    p0=finding_id,
                    p1=record.inherited_from,
                )
            )


def build_gate_verdict(
    *,
    run_id: str,
    target: ResolvedTarget,
    coverage: Sequence[LaneCoverage],
    merged: MergeResult,
    outcome: AdjudicationOutcome,
    dispositions: DispositionDocument,
    actor: str | None = None,
    actor_permission: str | None = None,
    inherited_run_id: str | None = None,
    inheritance: Mapping[str, DispositionInheritance] | None = None,
    inheritance_summary: InheritanceSummary | None = None,
) -> GateVerdict:
    if target.kind != "pr" or target.pr_number is None or target.base_sha is None:
        raise GateInvariantError(t("gate.error.gate_verdict_requires_a_PR", "en"))

    actionable = _actionable(merged, outcome)
    expected_ids = {group.key for group, _ in actionable}
    by_id = _dispositions_by_id(dispositions, expected_ids)
    _validate_inherited_from(
        by_id,
        inherited_run_id=inherited_run_id,
        inheritance=inheritance,
    )
    hunk_digests = hunk_sha256_by_id(target.diff)
    findings: list[GateFinding] = []
    accepted_blocker = False
    blocked = False
    for group, verdict in actionable:
        record = by_id[group.key]
        matched = inheritance.get(group.key) if inheritance is not None else None
        if record.decision is DispositionDecision.MUST_FIX:
            blocked = True
        if group.severity is Severity.BLOCKER and record.decision is DispositionDecision.ACCEPTED:
            accepted_blocker = True
            if actor_permission != "admin" or not actor:
                raise GateInvariantError(
                    t(
                        "gate.error.accepted_blocker_owner_unverified",
                        "en",
                        p0=group.key,
                        p1=actor or "<none>",
                        p2=actor_permission or "<none>",
                    )
                )
        findings.append(
            GateFinding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                line=group.line,
                severity=group.severity,
                verdict=verdict,
                disposition=record.decision,
                reason=record.reason,
                inherited_from=record.inherited_from,
                hunk_sha256=hunk_digests.get(group.hunk_id),
                body_sha256=_body_sha256(group),
                inheritance_tier=matched.tier if matched is not None else None,
                inheritance_blank_reason=(matched.blank_reason if matched is not None else None),
            )
        )

    counts = Counter(outcome.verdicts.values())
    return GateVerdict(
        run_id=run_id,
        repo=target.repo,
        pr_number=target.pr_number,
        anchor=GateAnchor(base_sha=target.base_sha, head_sha=target.head_sha),
        counts={verdict.value: counts[verdict] for verdict in Verdict},
        coverage=list(coverage),
        findings=findings,
        actor=actor if accepted_blocker else None,
        verdict="BLOCK" if blocked else "PASS",
        kind="completed",
        inheritance_summary=inheritance_summary,
    )


def requires_owner_authorization(
    merged: MergeResult,
    outcome: AdjudicationOutcome,
    dispositions: DispositionDocument,
    *,
    inherited_run_id: str | None = None,
    inheritance: Mapping[str, DispositionInheritance] | None = None,
) -> bool:
    actionable = _actionable(merged, outcome)
    by_id = _dispositions_by_id(dispositions, {group.key for group, _ in actionable})
    _validate_inherited_from(
        by_id,
        inherited_run_id=inherited_run_id,
        inheritance=inheritance,
    )
    return any(
        group.severity is Severity.BLOCKER
        and by_id[group.key].decision is DispositionDecision.ACCEPTED
        for group, _ in actionable
    )


def write_disposition_template(
    run_dir: Path,
    merged: MergeResult,
    outcome: AdjudicationOutcome,
    *,
    inheritance: Mapping[str, DispositionInheritance] | None = None,
) -> Path:
    records: list[tuple[dict[str, str], InheritanceTier | None, InheritanceBlankReason | None]] = []
    for group, _ in _actionable(merged, outcome):
        matched = inheritance.get(group.key) if inheritance is not None else None
        record = {
            "finding_id": group.key,
            "decision": (
                matched.decision.value
                if matched is not None
                else DispositionDecision.MUST_FIX.value
            ),
            "reason": matched.reason if matched is not None else "",
        }
        if matched is not None and matched.inherited_from is not None:
            record["inherited_from"] = matched.inherited_from
        records.append(
            (
                record,
                matched.tier if matched is not None else None,
                matched.blank_reason if matched is not None else None,
            )
        )
    lines = ["schema_version: 1", "dispositions:" if records else "dispositions: []"]
    for record, tier, blank_reason in records:
        dumped = yaml.safe_dump([record], sort_keys=False, allow_unicode=True).rstrip("\n")
        lines.extend(dumped.splitlines())
        if tier is InheritanceTier.UNIQUE_PAIR_STICKY:
            lines.append(f"  # inheritance_tier: {tier.value}")
        if blank_reason is not None:
            lines.append(f"  # blank_reason: {blank_reason.value}")
    path = run_dir / "gate-dispositions.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_gate_verdict(
    verdict: GateVerdict, *, locale: Locale = "en", presentation: PresentationConfig | None = None
) -> str:
    if presentation is not None:
        locale = presentation.locale
    display_name = presentation.display_name if presentation is not None else "rvw"
    lines = [
        t("gate.header", locale, p0=verdict.verdict, display_name=display_name),
        "",
        t("gate.run", locale, p0=verdict.run_id),
        t("gate.target", locale, p0=verdict.repo, p1=verdict.pr_number),
        t("gate.base", locale, p0=verdict.anchor.base_sha),
        t("gate.head", locale, p0=verdict.anchor.head_sha),
        "",
        t("gate.counts_heading", locale),
        "",
        "| CONFIRMED | REJECTED | UNCERTAIN |",
        "| ---: | ---: | ---: |",
        (
            f"| {verdict.counts['CONFIRMED']} | {verdict.counts['REJECTED']} | "
            f"{verdict.counts['UNCERTAIN']} |"
        ),
        "",
        t("gate.validity_heading", locale),
        "",
        t("report.coverage_columns", locale),
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {_cell(item.lane_id)} | {item.dispatched} | {item.valid} | {item.findings} | "
        f"{len(item.uncovered)} |"
        for item in verdict.coverage
    )
    uncovered = [item for item in verdict.coverage if item.uncovered]
    if uncovered:
        lines.extend(["", t("report.uncovered", locale)])
        for item in uncovered:
            hunk_ids = ", ".join(f"`{_cell(hunk_id)}`" for hunk_id in item.uncovered)
            lines.append(f"- `{_cell(item.lane_id)}`: {hunk_ids}")
    lines.extend(
        [
            "",
            t("gate.findings_heading", locale),
            "",
            (t("gate.findings_columns", locale)),
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        (
            f"| `{item.finding_id}` | {item.severity.value} | {item.verdict.value} | "
            f"{item.disposition.value} | "
            f"{f'`{_cell(item.inherited_from)}`' if item.inherited_from else '—'} | "
            f"{item.inheritance_tier.value if item.inheritance_tier else '—'} | "
            f"{item.inheritance_blank_reason.value if item.inheritance_blank_reason else '—'} | "
            f"{_cell(item.reason)} |"
        )
        for item in verdict.findings
    )
    if not verdict.findings:
        lines.append(t("gate.empty", locale))
    if verdict.actor is not None:
        lines.extend(["", t("gate.actor", locale, p0=verdict.actor)])
    if verdict.inheritance_summary is not None:
        summary = verdict.inheritance_summary
        reasons = ", ".join(f"{reason}={count}" for reason, count in summary.reasons.items()) or t(
            "common.none", locale
        )
        lines.extend(
            [
                "",
                t("gate.inheritance_heading", locale),
                "",
                t("gate.source_run", locale, p0=summary.source_run_id),
                (
                    t(
                        "gate.inheritance",
                        locale,
                        p0=summary.carried,
                        p1=summary.sticky,
                        p2=summary.prefilled,
                        p3=summary.blank,
                        p4=reasons,
                    )
                ),
            ]
        )
    if verdict.failures:
        lines.extend(
            [
                "",
                t("gate.failures_heading", locale),
                "",
                *(f"- {_cell(item)}" for item in verdict.failures),
            ]
        )
    return "\n".join(lines) + "\n"


def save_gate_verdict(
    run_dir: Path,
    verdict: GateVerdict,
    *,
    locale: Locale = "en",
    presentation: PresentationConfig | None = None,
) -> tuple[Path, Path]:
    json_path = run_dir / "gate-verdict.json"
    markdown_path = run_dir / "gate-verdict.md"
    json_path.write_text(
        f"{json.dumps(verdict.model_dump(mode='json'), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_gate_verdict(verdict, locale=locale, presentation=presentation), encoding="utf-8"
    )
    return json_path, markdown_path


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


_AUTHORIZATION_DIAGNOSTIC_LIMIT = 500
_REDACTED = "[REDACTED]"
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b")
_AUTHORIZATION_HEADER = re.compile(r"(?i)(\bAuthorization\s*:\s*)[^\u2028]*")
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{40,}\b")
_LONG_BASE64 = re.compile(
    r"(?<![A-Za-z0-9+/_-])"
    r"(?=[A-Za-z0-9+/_-]*[A-Za-z])"
    r"(?=[A-Za-z0-9+/_-]*\d)"
    r"[A-Za-z0-9+/_-]{40,}={0,2}"
    r"(?![A-Za-z0-9+/_=-])"
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ESCAPED_CONTROL_CHARACTER = re.compile(
    r"\\(?:u(?P<unicode>[0-9a-fA-F]{4})|x(?P<byte>[0-9a-fA-F]{2}))"
)


def _strip_escaped_control_character(match: re.Match[str]) -> str:
    raw_codepoint = match.group("unicode") or match.group("byte")
    character = chr(int(raw_codepoint, 16))
    if unicodedata.category(character) == "Cf":
        return ""
    if _CONTROL_CHARACTERS.fullmatch(character):
        return ""
    return match.group(0)


def _redact_subprocess_diagnostic(value: str) -> str:
    redacted = value.replace("\r\n", "\u2028").replace("\r", "\u2028").replace("\n", "\u2028")
    redacted = _ESCAPED_CONTROL_CHARACTER.sub(_strip_escaped_control_character, redacted)
    redacted = "".join(char for char in redacted if unicodedata.category(char) != "Cf")
    redacted = _CONTROL_CHARACTERS.sub("", redacted).strip()
    redacted = _GITHUB_TOKEN.sub(_REDACTED, redacted)
    redacted = _AUTHORIZATION_HEADER.sub(rf"\1{_REDACTED}", redacted)
    redacted = _BEARER_VALUE.sub(f"Bearer {_REDACTED}", redacted)
    redacted = _LONG_HEX.sub(_REDACTED, redacted)
    redacted = _LONG_BASE64.sub(_REDACTED, redacted)
    redacted = redacted.replace("\u2028", " ").strip()
    truncation_marker = "...[truncated]"
    if len(redacted) > _AUTHORIZATION_DIAGNOSTIC_LIMIT:
        redacted = (
            redacted[: _AUTHORIZATION_DIAGNOSTIC_LIMIT - len(truncation_marker)].rstrip()
            + truncation_marker
        )
    return redacted


def _authorization_error_detail(exc: OSError | subprocess.CalledProcessError) -> str:
    detail = str(exc)
    if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
        stderr = str(exc.stderr).strip()
        if stderr:
            detail = t("gate.error.", "en", p0=detail, p1=stderr)
    return _redact_subprocess_diagnostic(detail)


def query_pull_request(
    repo: str,
    pr_number: int,
    *,
    run: Callable[[list[str]], str] = _run,
) -> PullRequestState:
    try:
        raw = json.loads(run(["gh", "api", f"repos/{repo}/pulls/{pr_number}"]))
        return PullRequestState(
            base_sha=raw["base"]["sha"],
            head_sha=raw["head"]["sha"],
            state=raw["state"],
            merged=raw["merged"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            t("gate.error.invalid_pull_request_state_returned_for", "en", p0=repo, p1=pr_number)
        ) from exc


def verify_pull_request(anchor: GateAnchor, current: PullRequestState) -> None:
    if current.state != "open" or current.merged:
        raise GateInvariantError(t("gate.error.pull_request_must_remain_open", "en"))
    if current.base_sha != anchor.base_sha or current.head_sha != anchor.head_sha:
        raise GateInvariantError(
            t(
                "gate.error.stale_pull_request_anchor",
                "en",
                p0=anchor.base_sha,
                p1=anchor.head_sha,
                p2=current.base_sha,
                p3=current.head_sha,
            )
        )


def github_actor_permission(
    repo: str,
    *,
    run: Callable[[list[str]], str] = _run,
) -> tuple[str, str]:
    try:
        actor = run(["gh", "api", "user", "--jq", ".login"]).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitHubAuthorizationError(
            step="actor_lookup",
            actor=None,
            detail=_authorization_error_detail(exc),
        ) from exc
    if not actor:
        raise GitHubAuthorizationError(
            step="actor_lookup",
            actor=None,
            detail=t("gate.error.GitHub_returned_an_empty_authenticated", "en"),
        )
    try:
        permission = run(
            [
                "gh",
                "api",
                f"repos/{repo}/collaborators/{actor}/permission",
                "--jq",
                ".permission",
            ]
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitHubAuthorizationError(
            step="permission_lookup",
            actor=actor,
            detail=_authorization_error_detail(exc),
        ) from exc
    if not permission:
        raise GitHubAuthorizationError(
            step="permission_lookup",
            actor=actor,
            detail=t("gate.error.GitHub_returned_an_empty_repository", "en"),
        )
    return actor, permission


__all__ = [
    "ACTIONABLE_DISPOSITIONS_PAUSE",
    "DispositionDecision",
    "DispositionDocument",
    "DispositionInheritance",
    "DispositionRecord",
    "GateAnchor",
    "GateFinding",
    "GateInvariantError",
    "GatePlan",
    "GateVerdict",
    "GitHubAuthorizationError",
    "InheritanceBlankReason",
    "InheritanceSummary",
    "InheritanceTier",
    "PullRequestState",
    "build_gate_verdict",
    "github_actor_permission",
    "load_dispositions",
    "load_gate_plan",
    "match_inherited_dispositions",
    "provision_checkout",
    "query_pull_request",
    "render_gate_verdict",
    "requires_owner_authorization",
    "save_gate_plan",
    "save_gate_verdict",
    "summarize_inheritance",
    "validate_coverage",
    "verify_pull_request",
    "write_disposition_template",
]
