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
from rvw.discover import LaneCoverage
from rvw.hunks import hunk_sha256_by_id
from rvw.merge import CollapseGroup, MergeResult
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
    adjudicate_replicas: int = Field(default=3, ge=1)
    chunk_count: int = Field(ge=1)

    @field_validator("lane_ids")
    @classmethod
    def _lanes_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("gate plan lane IDs must be unique")
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
            raise ValueError("disposition reason must be nonblank")
        return value.strip()


class DispositionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    dispositions: list[DispositionRecord]


class InheritanceTier(StrEnum):
    EXACT_ID = "exact_id"
    UNIQUE_PAIR = "unique_pair"


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
        raise ValueError(f"could not load dispositions from {path}: {exc}") from exc
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
        raise GateInvariantError("expected replicas must be positive")
    if chunk_count < 1:
        raise GateInvariantError("expected chunk_count must be positive")
    if not coverage:
        raise GateInvariantError("coverage must be nonempty")

    coverage_ids = [item.lane_id for item in coverage]
    duplicates = sorted(lane_id for lane_id, count in Counter(coverage_ids).items() if count > 1)
    if duplicates:
        raise GateInvariantError(f"duplicate coverage lanes: {', '.join(duplicates)}")

    planned = set(planned_lane_ids)
    actual = set(coverage_ids)
    missing = sorted(planned - actual)
    unexpected = sorted(actual - planned)
    if not planned:
        detail = f"; unexpected coverage lanes: {', '.join(unexpected)}" if unexpected else ""
        raise GateInvariantError(f"planned lane set must be nonempty{detail}")
    if missing:
        raise GateInvariantError(f"missing planned coverage lanes: {', '.join(missing)}")
    if unexpected:
        raise GateInvariantError(f"unexpected coverage lanes: {', '.join(unexpected)}")

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
            raise GateInvariantError(
                f"lane {lane_id} dispatched {item.dispatched}; expected positive runs"
            )
        actual_runs = {(run.replica, run.chunk) for run in item.runs}
        missing_runs = sorted(expected_runs - actual_runs, key=lambda value: (value[1], value[0]))
        unexpected_runs = sorted(
            actual_runs - expected_runs, key=lambda value: (value[1], value[0])
        )
        if missing_runs:
            detail = ", ".join(
                f"replica {replica} chunk {chunk}" for replica, chunk in missing_runs
            )
            raise GateInvariantError(f"lane {lane_id} missing planned coverage runs: {detail}")
        if unexpected_runs:
            detail = ", ".join(
                f"replica {replica} chunk {chunk}" for replica, chunk in unexpected_runs
            )
            raise GateInvariantError(f"lane {lane_id} has unexpected coverage runs: {detail}")
        expected_count = replicas * chunk_count
        if item.dispatched != expected_count:
            raise GateInvariantError(
                f"lane {lane_id} dispatched {item.dispatched}; expected {expected_count} runs"
            )
        invalid_runs = [run for run in item.runs if not run.valid]
        if invalid_runs:
            run = invalid_runs[0]
            raise GateInvariantError(
                f"lane {lane_id} replica {run.replica} chunk {run.chunk} invalid: "
                f"{run.invalid_reason}"
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
            "adjudication outcome keys must exactly match merged finding keys: "
            + "; ".join(details)
        )
    actionable: list[tuple[CollapseGroup, Verdict]] = []
    for group in merged.groups:
        verdict = outcome.verdicts.get(group.key)
        if verdict is None:
            raise GateInvariantError(f"missing adjudication verdict for finding {group.key}")
        if verdict in {Verdict.CONFIRMED, Verdict.UNCERTAIN}:
            actionable.append((group, verdict))
    return actionable


def _dispositions_by_id(
    document: DispositionDocument, expected_ids: set[str]
) -> dict[str, DispositionRecord]:
    ids = [record.finding_id for record in document.dispositions]
    duplicates = sorted(finding_id for finding_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise GateInvariantError(f"duplicate disposition finding IDs: {', '.join(duplicates)}")
    actual_ids = set(ids)
    unknown = sorted(actual_ids - expected_ids)
    if unknown:
        raise GateInvariantError(f"unknown disposition finding IDs: {', '.join(unknown)}")
    missing = sorted(expected_ids - actual_ids)
    if missing:
        raise GateInvariantError(f"missing disposition finding IDs: {', '.join(missing)}")
    return {record.finding_id: record for record in document.dispositions}


def _body_sha256(group: CollapseGroup) -> str:
    """Digest the complete order-insensitive body set for a collapsed finding."""

    if not group.bodies:
        raise GateInvariantError(f"collapsed finding {group.key} must contain at least one body")
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
        results[group.key] = DispositionInheritance(
            finding_id=group.key,
            decision=DispositionDecision.MUST_FIX,
            reason=inherited.reason,
            inherited_from=inherited_run_id,
            tier=InheritanceTier.UNIQUE_PAIR,
            blank_reason=demotion_reason or InheritanceBlankReason.FINDING_ID_CHANGED,
        )
    return results


def summarize_inheritance(
    inheritance: Mapping[str, DispositionInheritance],
    *,
    source_run_id: str,
) -> InheritanceSummary:
    carried = 0
    prefilled = 0
    blank = 0
    reasons: Counter[InheritanceBlankReason] = Counter()
    for result in inheritance.values():
        if result.tier is InheritanceTier.EXACT_ID:
            carried += 1
        elif result.reason:
            prefilled += 1
        else:
            blank += 1
        if result.blank_reason is not None:
            reasons[result.blank_reason] += 1
    return InheritanceSummary(
        source_run_id=source_run_id,
        carried=carried,
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
                "inherited_from_unbound: "
                f"finding {finding_id} claims {record.inherited_from!r} without a matching "
                "selected inheritance source"
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
        raise GateInvariantError("gate verdict requires a PR target with base and head anchors")

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
                    "accepted_blocker_owner_unverified: "
                    f"finding_id={group.key} actor={actor or '<none>'} "
                    f"permission={actor_permission or '<none>'}; repository admin required"
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
    records: list[tuple[dict[str, str], InheritanceBlankReason | None]] = []
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
        records.append((record, matched.blank_reason if matched is not None else None))
    lines = ["schema_version: 1", "dispositions:" if records else "dispositions: []"]
    for record, blank_reason in records:
        dumped = yaml.safe_dump([record], sort_keys=False, allow_unicode=True).rstrip("\n")
        lines.extend(dumped.splitlines())
        if blank_reason is not None:
            lines.append(f"  # blank_reason: {blank_reason.value}")
    path = run_dir / "gate-dispositions.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_gate_verdict(verdict: GateVerdict) -> str:
    lines = [
        f"# rvw gate — {verdict.verdict}",
        "",
        f"Run ID: `{verdict.run_id}`",
        f"Target: `{verdict.repo}#{verdict.pr_number}`",
        f"Base SHA: `{verdict.anchor.base_sha}`",
        f"Head SHA: `{verdict.anchor.head_sha}`",
        "",
        "## Verdict counts",
        "",
        "| CONFIRMED | REJECTED | UNCERTAIN |",
        "| ---: | ---: | ---: |",
        (
            f"| {verdict.counts['CONFIRMED']} | {verdict.counts['REJECTED']} | "
            f"{verdict.counts['UNCERTAIN']} |"
        ),
        "",
        "## Lane validity",
        "",
        "| Lane | Dispatched | Valid | Findings |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {_cell(item.lane_id)} | {item.dispatched} | {item.valid} | {item.findings} |"
        for item in verdict.coverage
    )
    lines.extend(
        [
            "",
            "## Gate findings",
            "",
            "| Finding ID | Severity | Verdict | Disposition | Inherited from | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        (
            f"| `{item.finding_id}` | {item.severity.value} | {item.verdict.value} | "
            f"{item.disposition.value} | "
            f"{f'`{_cell(item.inherited_from)}`' if item.inherited_from else '—'} | "
            f"{_cell(item.reason)} |"
        )
        for item in verdict.findings
    )
    if not verdict.findings:
        lines.append("| — | — | — | — | — | No actionable findings |")
    if verdict.actor is not None:
        lines.extend(["", f"Verified blocker-acceptance actor: `{verdict.actor}`"])
    if verdict.inheritance_summary is not None:
        summary = verdict.inheritance_summary
        reasons = (
            ", ".join(f"{reason}={count}" for reason, count in summary.reasons.items()) or "none"
        )
        lines.extend(
            [
                "",
                "## Inheritance summary",
                "",
                f"Source run: `{summary.source_run_id}`",
                (
                    f"Carried: {summary.carried}; prefilled: {summary.prefilled}; "
                    f"blank: {summary.blank}; reasons: {reasons}"
                ),
            ]
        )
    if verdict.failures:
        lines.extend(["", "## Failures", "", *(f"- {_cell(item)}" for item in verdict.failures)])
    return "\n".join(lines) + "\n"


def save_gate_verdict(run_dir: Path, verdict: GateVerdict) -> tuple[Path, Path]:
    json_path = run_dir / "gate-verdict.json"
    markdown_path = run_dir / "gate-verdict.md"
    json_path.write_text(
        f"{json.dumps(verdict.model_dump(mode='json'), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_gate_verdict(verdict), encoding="utf-8")
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
            detail = f"{detail}; stderr: {stderr}"
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
        raise ValueError(f"invalid pull-request state returned for {repo}#{pr_number}") from exc


def verify_pull_request(anchor: GateAnchor, current: PullRequestState) -> None:
    if current.state != "open" or current.merged:
        raise GateInvariantError("pull request must remain open and unmerged")
    if current.base_sha != anchor.base_sha or current.head_sha != anchor.head_sha:
        raise GateInvariantError(
            "stale pull request anchor: "
            f"expected {anchor.base_sha}/{anchor.head_sha}, "
            f"found {current.base_sha}/{current.head_sha}"
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
            detail="GitHub returned an empty authenticated actor",
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
            detail="GitHub returned an empty repository permission",
        )
    return actor, permission


def provision_checkout(
    *,
    repo: str,
    pr_number: int,
    head_sha: str,
    destination: Path,
    run: Callable[[list[str]], str] = _run,
) -> Path:
    run(["gh", "repo", "clone", repo, str(destination), "--", "--no-checkout"])
    run(
        [
            "git",
            "-C",
            str(destination),
            "fetch",
            "--no-tags",
            "origin",
            f"refs/pull/{pr_number}/head",
        ]
    )
    run(["git", "-C", str(destination), "checkout", "--detach", head_sha])
    actual_head = run(["git", "-C", str(destination), "rev-parse", "HEAD"]).strip()
    if actual_head != head_sha:
        raise GateInvariantError(
            f"checkout HEAD {actual_head or '<empty>'} does not match captured head {head_sha}"
        )
    status = run(
        ["git", "-C", str(destination), "status", "--porcelain=v1", "--untracked-files=all"]
    ).strip()
    if status:
        raise GateInvariantError("disposable checkout must be clean")
    return destination


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
