"""Strict terminal status contract shared by persistence, CLI JSON, and reports."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.adjudicate import AdjudicationAttempt
from rvw.discover import DiscoverResult
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


class SkippedLane(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    reason: str


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
    skipped_lanes: list[SkippedLane] = Field(default_factory=list)
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


def skipped_lanes(discovered: DiscoverResult) -> list[SkippedLane]:
    return [
        SkippedLane(lane_id=lane.lane_id, reason=lane.skipped_reason)
        for lane in discovered.coverage
        if lane.skipped_reason is not None
    ]


def summarize_run(
    run_id: str,
    discovered: DiscoverResult,
    *,
    error: RunError | None = None,
    build: BuildProvenance | None = None,
) -> RunSummary:
    totals = coverage_totals(discovered)
    failures = failed_lanes(discovered)
    skipped = skipped_lanes(discovered)
    if error is not None or ((failures or skipped) and totals.valid == 0):
        status = ReviewStatus.FAILED
    elif failures or skipped:
        status = ReviewStatus.DEGRADED
    else:
        status = ReviewStatus.COMPLETE
    return RunSummary(
        run_id=run_id,
        status=status,
        failed_lanes=failures,
        skipped_lanes=skipped,
        coverage_totals=totals,
        error=error,
        build=build or current_build_provenance(),
    )


def running_summary(run_id: str) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        status=ReviewStatus.RUNNING,
        failed_lanes=[],
        skipped_lanes=[],
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
    "SkippedLane",
    "coverage_totals",
    "failed_lanes",
    "running_summary",
    "skipped_lanes",
    "summarize_run",
]
