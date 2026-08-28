"""DISCOVER orchestration: activate, prompt, dispatch, and enrich lane findings."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.diffbudget import DiffBudgetReport, DiffChunk, apply_diff_budget, require_reviewable_diff
from rvw.dispatch import (
    CORRECTABLE_INVALID_REASONS,
    DEFAULT_CONCURRENCY,
    DEFAULT_DEADLINE_SECONDS,
    PlannedRun,
    dispatch_outcome,
)
from rvw.hostslots import HostSlotGate
from rvw.hunks import hunk_for_line, is_anchorable, parse_hunks
from rvw.lane import Lane, load_lane
from rvw.prompts import build_chunk_context, build_lane_prompt, build_retry_feedback
from rvw.registry import Registry
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, Runtime
from rvw.schema import Finding, Tier
from rvw.target import ResolvedTarget


class EnrichedFinding(Finding):
    """A runtime finding attributed to its lane and replica."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    replica: int = Field(ge=1)


class RunAttempt(BaseModel):
    """Validity of one execution attempt for a planned run."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    valid: bool
    invalid_reason: str | None

    @model_validator(mode="after")
    def _validity_must_match_reason(self) -> RunAttempt:
        if self.valid and self.invalid_reason is not None:
            raise ValueError("valid run attempts cannot have an invalid_reason")
        if not self.valid and (self.invalid_reason is None or not self.invalid_reason.strip()):
            raise ValueError("invalid run attempts require an invalid_reason")
        return self


class RunCoverage(BaseModel):
    """Validity and yield for one planned replica-chunk execution."""

    model_config = ConfigDict(extra="forbid")

    replica: int = Field(ge=1)
    chunk: int = Field(ge=1)
    valid: bool
    findings: int = Field(ge=0)
    invalid_reason: str | None
    attempts: list[RunAttempt] = Field(default_factory=list)
    diagnostic: RunDiagnostic | None = None

    @model_validator(mode="after")
    def _validity_must_match_reason(self) -> RunCoverage:
        if self.valid and self.invalid_reason is not None:
            raise ValueError("valid coverage runs cannot have an invalid_reason")
        if not self.valid and (self.invalid_reason is None or not self.invalid_reason.strip()):
            raise ValueError("invalid coverage runs require an invalid_reason")
        if not self.valid and self.findings:
            raise ValueError("invalid coverage runs cannot have findings")
        if self.valid and self.diagnostic is not None:
            raise ValueError("valid coverage runs cannot have a diagnostic")
        if self.attempts:
            attempt_numbers = [attempt.attempt for attempt in self.attempts]
            if attempt_numbers != list(range(1, len(self.attempts) + 1)):
                raise ValueError("coverage run attempts must be numbered 1..N in order")
            final_attempt = self.attempts[-1]
            if (
                final_attempt.valid != self.valid
                or final_attempt.invalid_reason != self.invalid_reason
            ):
                raise ValueError("final coverage attempt must match the coverage run status")
        return self


class LaneCoverage(BaseModel):
    """DISCOVER aggregate and exact run coverage for one activated lane."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    dispatched: int = Field(ge=0)
    valid: int = Field(ge=0)
    findings: int = Field(ge=0)
    runs: list[RunCoverage]
    skipped_reason: Literal["brief_unavailable"] | None = None

    @model_validator(mode="after")
    def _aggregates_must_match_runs(self) -> LaneCoverage:
        if self.skipped_reason is not None:
            if self.dispatched or self.valid or self.findings or self.runs:
                raise ValueError("skipped coverage must have no dispatches or runs")
            return self
        identities = [(run.replica, run.chunk) for run in self.runs]
        if len(identities) != len(set(identities)):
            raise ValueError("coverage run identities must be unique")
        if self.dispatched != len(self.runs):
            raise ValueError("dispatched must equal the number of coverage runs")
        if self.valid != sum(run.valid for run in self.runs):
            raise ValueError("valid must equal the number of valid coverage runs")
        if self.findings != sum(run.findings for run in self.runs):
            raise ValueError("findings must equal the coverage run finding total")
        return self


@dataclass(frozen=True)
class DiscoverResult:
    lane_results: dict[str, list[RunResult]]
    findings: list[EnrichedFinding]
    coverage: list[LaneCoverage]
    budget: DiffBudgetReport | None = None


@dataclass(frozen=True)
class DiscoveryPlan:
    """The exact initial prompts and bounded run shape for DISCOVER."""

    lanes: list[Lane]
    chunks: list[DiffChunk]
    budget: DiffBudgetReport
    runs: list[PlannedRun]
    skipped_lane_ids: set[str] = field(default_factory=set)

    @property
    def initial_runs(self) -> int:
        return len(self.runs)

    @property
    def retry_upper_bound(self) -> int:
        return self.initial_runs * 2

    @property
    def initial_prompt_characters(self) -> int:
        return sum(len(run.prompt) for run in self.runs)


class IncompleteDiscoveryError(RuntimeError):
    """DISCOVER finished without any valid output for at least one lane/chunk."""

    def __init__(self, lane_chunks: set[tuple[str, int]]) -> None:
        self.lane_chunks = lane_chunks
        labels = ", ".join(f"{lane}:chunk-{chunk}" for lane, chunk in sorted(lane_chunks))
        super().__init__(f"incomplete discovery: no valid output for {labels}")


def resolve_lane_path(lanes_root: Path, lane_id: str, tier: Tier) -> Path:
    """Resolve a lane ID beneath the directory owned by its registry layer tier."""

    segments = lane_id.split("/")
    if not all(segment and segment not in {".", ".."} for segment in segments):
        raise ValueError(f"invalid lane id: {lane_id!r}")
    relative_segments = segments[1:] if segments[0] == tier.value else segments
    if not relative_segments:
        raise ValueError(f"invalid lane id: {lane_id!r}")
    attempted = lanes_root / tier.value / Path(*relative_segments).with_suffix(".md")
    if not attempted.is_file():
        raise FileNotFoundError(f"lane document not found; attempted path: {attempted}")
    return attempted


def _active_lane_owners(
    registry: Registry,
    target: ResolvedTarget,
    lane_filter: Sequence[str] | None,
) -> list[tuple[str, Tier]]:
    selected = set(lane_filter) if lane_filter is not None else None
    owners: list[tuple[str, Tier]] = []
    seen: set[str] = set()
    for layer in registry.activate(target.repo, target.changed_paths):
        for lane_id in layer.lanes:
            if (selected is None or lane_id in selected) and lane_id not in seen:
                owners.append((lane_id, layer.tier))
                seen.add(lane_id)
    return owners


def _effective_brief(
    target: ResolvedTarget,
    brief: str | None,
    brief_source: str | None,
) -> tuple[str | None, str | None]:
    del brief_source
    if brief is not None:
        return brief, "operator"
    if target.pr_title is not None or target.pr_body is not None:
        return f"{target.pr_title or ''}\n\n{target.pr_body or ''}", "pr_body"
    return None, None


def _coverage_attempts(
    result: RunResult,
    initial_by_key: Mapping[tuple[str, int, int], RunResult],
    prior_attempts: Mapping[tuple[str, int, int], Sequence[RunResult]],
) -> list[RunAttempt]:
    key = (result.lane_id, result.replica, result.chunk)
    initial = initial_by_key.get((result.lane_id, result.replica, result.chunk))
    prior_results = list(prior_attempts.get(key, ()))
    attempt_results = (
        prior_results
        if initial is None and any(result is prior for prior in prior_results)
        else [*prior_results, *([result] if initial is None else [initial, result])]
    )
    return [
        RunAttempt(
            attempt=attempt,
            valid=attempt_result.status is RunStatus.VALID,
            invalid_reason=attempt_result.invalid_reason,
        )
        for attempt, attempt_result in enumerate(attempt_results, start=1)
    ]


def remaining_discovery_plan(
    plan: DiscoveryPlan,
    completed_results: Mapping[tuple[str, int, int], RunResult],
) -> DiscoveryPlan:
    """Return the exact remaining work after compatible valid reuse."""

    return replace(
        plan,
        runs=[
            run
            for run in plan.runs
            if (run.lane.id, run.replica, run.chunk) not in completed_results
        ],
    )


def plan_discovery(
    *,
    registry: Registry,
    lanes_root: Path,
    target: ResolvedTarget,
    brief: str | None = None,
    brief_source: str | None = None,
    replicas: int = 1,
    lane_filter: Sequence[str] | None = None,
) -> DiscoveryPlan:
    """Build every initial discovery prompt without starting runtime work."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")

    owners = _active_lane_owners(registry, target, lane_filter)
    lanes = [load_lane(resolve_lane_path(lanes_root, lane_id, tier)) for lane_id, tier in owners]
    effective_brief, effective_brief_source = _effective_brief(target, brief, brief_source)
    chunks, budget = apply_diff_budget(target.diff)
    require_reviewable_diff(budget, source="target")
    covered_rules = {lane.id: lane.rules for lane in lanes}
    skipped_lane_ids = {
        lane.id
        for lane in lanes
        if lane.tier is Tier.DYNAMIC and lane.requires_brief and effective_brief is None
    }
    runs = [
        PlannedRun(
            lane=lane,
            prompt=build_lane_prompt(
                lane,
                diff=chunk.text,
                brief=effective_brief,
                brief_source=effective_brief_source,
                covered_rules=covered_rules,
                chunk_context=build_chunk_context(
                    chunk=chunk.index,
                    chunk_count=len(chunks),
                    chunk_files=chunk.files,
                    kept_files=budget.kept_files,
                ),
            ),
            replica=replica,
            chunk=chunk.index,
            chunk_count=len(chunks),
        )
        for lane in lanes
        if lane.id not in skipped_lane_ids
        for chunk in chunks
        for replica in range(1, replicas + 1)
    ]
    return DiscoveryPlan(
        lanes=lanes,
        chunks=chunks,
        budget=budget,
        runs=runs,
        skipped_lane_ids=skipped_lane_ids,
    )


async def discover(
    *,
    registry: Registry,
    lanes_root: Path,
    target: ResolvedTarget,
    runtime: Runtime,
    out_root: Path,
    brief: str | None = None,
    brief_source: str | None = None,
    replicas: int = 1,
    concurrency: int = DEFAULT_CONCURRENCY,
    lane_filter: Sequence[str] | None = None,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    host_gate: HostSlotGate | None = None,
    planned: DiscoveryPlan | None = None,
    completed_results: Mapping[tuple[str, int, int], RunResult] | None = None,
    prior_attempts: Mapping[tuple[str, int, int], Sequence[RunResult]] | None = None,
    prior_retry_lane_chunks: set[tuple[str, int]] | None = None,
    on_progress: Callable[[RunResult], None] | None = None,
) -> DiscoverResult:
    """Run all activated lanes in one dispatch call and enrich valid findings."""

    plan = planned or plan_discovery(
        registry=registry,
        lanes_root=lanes_root,
        target=target,
        brief=brief,
        brief_source=brief_source,
        replicas=replicas,
        lane_filter=lane_filter,
    )
    attempt_history = {key: list(attempts) for key, attempts in (prior_attempts or {}).items()}
    reusable = dict(completed_results or {})
    for key, attempts in attempt_history.items():
        valid_attempts = [attempt for attempt in attempts if attempt.status is RunStatus.VALID]
        if valid_attempts:
            reusable[key] = valid_attempts[-1]
    pending_plan = remaining_discovery_plan(plan, reusable)
    prior_retry = set(prior_retry_lane_chunks or ())
    prior_invalid_lane_chunks = {
        (lane_id, chunk)
        for (lane_id, _replica, chunk), attempts in attempt_history.items()
        if attempts and attempts[-1].status is RunStatus.INVALID
    }
    pending_by_lane_chunk: dict[tuple[str, int], list[PlannedRun]] = {}
    for run in pending_plan.runs:
        pending_by_lane_chunk.setdefault((run.lane.id, run.chunk), []).append(run)
    resume_retry_feedback: dict[tuple[str, int], str] = {}
    for lane_chunk, runs in pending_by_lane_chunk.items():
        prior_results = [
            attempt_history.get((run.lane.id, run.replica, run.chunk), [])[-1:] for run in runs
        ]
        if (
            lane_chunk not in prior_retry
            and len(prior_results) == len(runs)
            and all(prior_results)
            and all(
                result.invalid_reason in CORRECTABLE_INVALID_REASONS
                for result_list in prior_results
                for result in result_list
            )
        ):
            resume_retry_feedback[lane_chunk] = build_retry_feedback(
                [
                    f"replica {run.replica}: {attempt_history[(run.lane.id, run.replica, run.chunk)][-1].invalid_reason}"
                    for run in runs
                ]
            )
    attempt_numbers_by_key = {
        (run.lane.id, run.replica, run.chunk): len(
            attempt_history.get((run.lane.id, run.replica, run.chunk), ())
        )
        + 1
        for run in pending_plan.runs
    }
    dispatched = await dispatch_outcome(
        pending_plan.runs,
        runtime,
        out_root=out_root,
        concurrency=concurrency,
        deadline_seconds=deadline_seconds,
        host_gate=host_gate,
        on_progress=on_progress,
        prior_valid_lane_chunks={(lane_id, chunk) for lane_id, _replica, chunk in reusable},
        prior_retry_lane_chunks=prior_retry | prior_invalid_lane_chunks,
        attempt_numbers_by_key=attempt_numbers_by_key,
        resume_retry_feedback_by_lane_chunk=resume_retry_feedback,
    )
    raw_results = [*reusable.values(), *dispatched.results]

    results_by_lane_chunk: dict[tuple[str, int], list[RunResult]] = {}
    for result in raw_results:
        results_by_lane_chunk.setdefault((result.lane_id, result.chunk), []).append(result)
    incomplete_lane_chunks = {
        lane_chunk
        for lane_chunk, lane_results in results_by_lane_chunk.items()
        if lane_results and all(result.status is RunStatus.INVALID for result in lane_results)
    }
    if incomplete_lane_chunks:
        raise IncompleteDiscoveryError(incomplete_lane_chunks)

    lane_results: dict[str, list[RunResult]] = {lane.id: [] for lane in plan.lanes}
    for result in raw_results:
        lane_results[result.lane_id].append(result)

    hunks = parse_hunks(target.diff)
    enriched: list[EnrichedFinding] = []
    finding_counts: dict[tuple[str, int, int], int] = {}
    for result in raw_results:
        if result.status is not RunStatus.VALID or result.output is None:
            continue
        for finding in result.output.findings:
            hunk = hunk_for_line(hunks, finding.file, finding.line)
            anchorable = is_anchorable(hunks, finding.file, finding.line)
            enriched.append(
                EnrichedFinding.model_validate(
                    {
                        **finding.model_dump(),
                        "hunk_id": hunk.hunk_id if hunk is not None else f"{finding.file}:*",
                        "anchorable": anchorable,
                        "lane_id": result.lane_id,
                        "replica": result.replica,
                    }
                )
            )
            key = (result.lane_id, result.replica, result.chunk)
            finding_counts[key] = finding_counts.get(key, 0) + 1

    coverage: list[LaneCoverage] = []
    for lane in plan.lanes:
        if lane.id in plan.skipped_lane_ids:
            coverage.append(
                LaneCoverage(
                    lane_id=lane.id,
                    dispatched=0,
                    valid=0,
                    findings=0,
                    runs=[],
                    skipped_reason="brief_unavailable",
                )
            )
            continue
        results = lane_results[lane.id]
        valid = sum(result.status is RunStatus.VALID for result in results)
        runs = [
            RunCoverage(
                replica=result.replica,
                chunk=result.chunk,
                valid=result.status is RunStatus.VALID,
                findings=finding_counts.get((result.lane_id, result.replica, result.chunk), 0),
                invalid_reason=result.invalid_reason,
                attempts=_coverage_attempts(result, dispatched.initial_by_key, attempt_history),
                diagnostic=result.diagnostic,
            )
            for result in results
        ]
        coverage.append(
            LaneCoverage(
                lane_id=lane.id,
                dispatched=len(runs),
                valid=valid,
                findings=sum(run.findings for run in runs),
                runs=runs,
            )
        )

    return DiscoverResult(
        lane_results=lane_results,
        findings=enriched,
        coverage=coverage,
        budget=plan.budget,
    )


__all__: list[str] = [
    "DiscoverResult",
    "DiscoveryPlan",
    "EnrichedFinding",
    "IncompleteDiscoveryError",
    "LaneCoverage",
    "RunAttempt",
    "RunCoverage",
    "discover",
    "plan_discovery",
    "remaining_discovery_plan",
    "resolve_lane_path",
]
