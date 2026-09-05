"""Strict terminal status contract shared by persistence, CLI JSON, and reports."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.adjudicate import AdjudicationAttempt, AdjudicationOutcome
from rvw.discover import DiscoverResult
from rvw.merge import MergeResult
from rvw.provenance import BuildProvenance, current_build_provenance
from rvw.runtimes import RunDiagnostic


class ReviewStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    FAILED = "failed"


class CoverageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dispatched: int = Field(ge=0)
    valid: int = Field(ge=0)
    findings: int = Field(ge=0)


class LaneFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    replica: int = Field(ge=1)
    chunk: int = Field(ge=1)
    reason: str
    diagnostic: RunDiagnostic | None = None

    @model_validator(mode="after")
    def _reason_must_not_be_blank(self) -> LaneFailure:
        if not self.reason.strip():
            raise ValueError("lane failure reason must not be blank")
        return self


class FailedLane(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    failures: list[LaneFailure]


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    reason: str
    message: str
    attempts: list[AdjudicationAttempt] = Field(default_factory=list)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    run_id: str
    status: ReviewStatus
    failed_lanes: list[FailedLane]
    coverage_totals: CoverageTotals
    error: RunError | None
    build: BuildProvenance = Field(default_factory=current_build_provenance)


def coverage_totals(discovered: DiscoverResult) -> CoverageTotals:
    return CoverageTotals(
        dispatched=sum(item.dispatched for item in discovered.coverage),
        valid=sum(item.valid for item in discovered.coverage),
        findings=sum(item.findings for item in discovered.coverage),
    )


def failed_lanes(discovered: DiscoverResult) -> list[FailedLane]:
    failed: list[FailedLane] = []
    for lane in discovered.coverage:
        failures = [
            LaneFailure(
                replica=run.replica,
                chunk=run.chunk,
                reason=run.invalid_reason or "unknown",
                diagnostic=run.diagnostic,
            )
            for run in lane.runs
            if not run.valid
        ]
        if failures:
            failed.append(FailedLane(lane_id=lane.lane_id, failures=failures))
    return failed


def summarize_run(
    run_id: str,
    discovered: DiscoverResult,
    *,
    error: RunError | None = None,
    build: BuildProvenance | None = None,
) -> RunSummary:
    totals = coverage_totals(discovered)
    failures = failed_lanes(discovered)
    if error is not None or (failures and totals.valid == 0):
        status = ReviewStatus.FAILED
    elif failures:
        status = ReviewStatus.DEGRADED
    else:
        status = ReviewStatus.COMPLETE
    return RunSummary(
        run_id=run_id,
        status=status,
        failed_lanes=failures,
        coverage_totals=totals,
        error=error,
        build=build or current_build_provenance(),
    )


def running_summary(run_id: str) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        status=ReviewStatus.RUNNING,
        failed_lanes=[],
        coverage_totals=CoverageTotals(dispatched=0, valid=0, findings=0),
        error=None,
        build=current_build_provenance(),
    )


__all__ = [
    "CoverageTotals",
    "FailedLane",
    "LaneFailure",
    "ReviewStatus",
    "RunError",
    "RunSummary",
    "coverage_totals",
    "failed_lanes",
    "running_summary",
    "summarize_run",
]


# The policy-gated execution envelope is separate from run.json (stage health)
# and outcome.json (adjudication), which keep their existing strict schemas.
class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProcessTarget(ContractModel):
    repo: str | None = None
    pr: int | None = Field(default=None, ge=1)
    base: str | None = None
    head: str | None = None


class EffectivePolicySource(ContractModel):
    source: Literal["explicit", "repository", "external", "package"] | None = None
    path: str | None = None


class RuntimeSettings(ContractModel):
    replicas: int = Field(default=1, ge=1)
    adjudicate_replicas: int = Field(default=3, ge=1)
    concurrency: int = Field(default=8, ge=1)
    deadline: int = Field(default=600, ge=1, le=1800)
    discovery_mode: Literal["agentic", "inline"] = "agentic"
    publish: Literal["none", "github-comment"] = "none"
    host_concurrency: int = Field(default=12, ge=0)
    sandbox: Literal["read-only", "danger-full-access"] = "read-only"


class ProcessFailure(ContractModel):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ArtifactEntry(ContractModel):
    path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _relative_path(self) -> ArtifactEntry:
        if (
            self.path.startswith("/")
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
        ):
            raise ValueError("artifact path must be a contained relative POSIX path")
        return self


class SDKObservations(ContractModel):
    exit_code: int | None = None
    signal: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    command: str | None = None


class ProcessResult(ContractModel):
    schema_version: Literal[1] = 1
    run_id: str
    target: ProcessTarget = Field(default_factory=ProcessTarget)
    status: Literal["pass", "block", "invalid", "infra_failed"] = "infra_failed"
    exit_code: Literal[0, 1, 2, 3] = 3
    duration_ms: int = Field(default=0, ge=0)
    command: list[str]
    effective_policy: EffectivePolicySource = Field(default_factory=EffectivePolicySource)
    lane_sources: dict[str, int] = Field(default_factory=dict)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    failure: ProcessFailure | None = None
    artifacts: list[ArtifactEntry] = Field(default_factory=list)
    sdk_observations: SDKObservations | None = None

    @model_validator(mode="after")
    def _status_matches_exit(self) -> ProcessResult:
        expected = {"pass": 0, "block": 1, "invalid": 2, "infra_failed": 3}
        if self.exit_code != expected[self.status]:
            raise ValueError("status and exit_code disagree")
        if (self.status in {"invalid", "infra_failed"}) != (self.failure is not None):
            raise ValueError("invalid and infra_failed require failure; pass/block forbid it")
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate artifact path")
        if any(count < 0 for count in self.lane_sources.values()):
            raise ValueError("lane source counts must be nonnegative")
        return self


class SummaryLanes(ContractModel):
    dispatched: int = Field(default=0, ge=0)
    valid: int = Field(default=0, ge=0)
    uncovered: int = Field(default=0, ge=0)


class FindingCounts(ContractModel):
    blocker: int = Field(default=0, ge=0)
    warning: int = Field(default=0, ge=0)
    suggestion: int = Field(default=0, ge=0)


class VerdictCounts(ContractModel):
    CONFIRMED: int = Field(default=0, ge=0)
    REJECTED: int = Field(default=0, ge=0)
    UNCERTAIN: int = Field(default=0, ge=0)


class ExecutionSummary(ContractModel):
    schema_version: Literal[1] = 1
    lanes: SummaryLanes = Field(default_factory=SummaryLanes)
    findings: FindingCounts = Field(default_factory=FindingCounts)
    verdicts: VerdictCounts = Field(default_factory=VerdictCounts)
    blockers: list[str] = Field(default_factory=list)
    markdown: str = "Review has not completed."


def execution_summary(
    discovered: DiscoverResult,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    blockers: list[str],
) -> ExecutionSummary:
    """Compute presentation facts once for every review adapter."""
    lanes = SummaryLanes(
        dispatched=len(discovered.coverage),
        valid=sum(lane.valid > 0 for lane in discovered.coverage),
        uncovered=sum(len(lane.uncovered) for lane in discovered.coverage),
    )
    counts = Counter(group.severity.value for group in merged.groups)
    findings = FindingCounts(**{key: counts[key] for key in ("blocker", "warning", "suggestion")})
    votes = Counter(v.value for v in outcome.verdicts.values()) if outcome else Counter()
    verdicts = VerdictCounts(**{key: votes[key] for key in ("CONFIRMED", "REJECTED", "UNCERTAIN")})
    markdown = (
        f"Lanes: {lanes.valid}/{lanes.dispatched} valid; {lanes.uncovered} uncovered hunks.\n\n"
        f"Findings: {findings.blocker} blocker, {findings.warning} warning, "
        f"{findings.suggestion} suggestion.\n\n"
        f"Verdicts: {verdicts.CONFIRMED} confirmed, {verdicts.REJECTED} rejected, "
        f"{verdicts.UNCERTAIN} uncertain.\n\nPolicy blockers: {len(blockers)}."
    )
    return ExecutionSummary(
        lanes=lanes, findings=findings, verdicts=verdicts, blockers=blockers, markdown=markdown
    )
