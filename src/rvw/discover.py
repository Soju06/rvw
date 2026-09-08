"""DISCOVER orchestration: activate, prompt, dispatch, and enrich lane findings."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.checkout import CheckoutVerificationError
from rvw.diffbudget import DiffBudgetReport, apply_diff_budget, require_reviewable_diff
from rvw.dispatch import (
    DEFAULT_CONCURRENCY,
    DEFAULT_DEADLINE_SECONDS,
    PlannedRun,
    dispatch_outcome,
)
from rvw.hostslots import HostSlotGate
from rvw.hunks import Hunk, hunk_for_line, is_anchorable, parse_hunks
from rvw.lane import load_lane
from rvw.prompts import build_agentic_lane_prompt, build_chunk_context, build_lane_prompt
from rvw.registry import EffectiveRegistry, Registry
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, Runtime
from rvw.schema import Finding, Tier
from rvw.target import ResolvedTarget

_COVERED_RANGE = re.compile(r"^(?P<file>.+):(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$")

# The runtime classifies its own deadline kill as this normalized reason.
DEAD_BY_TIMEOUT_REASON = "exit_nonzero:124"
RedispatchSkip = Literal["dead_by_timeout"]
AttemptWave = Literal["initial", "retry", "coverage_redispatch"]


class DiscoveryMode(StrEnum):
    AGENTIC = "agentic"
    INLINE = "inline"


class EnrichedFinding(Finding):
    """A runtime finding attributed to its lane and replica."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    replica: int = Field(ge=1)


class RunAttempt(BaseModel):
    """Validity, wave, and wall time of one execution attempt for a planned run."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    wave: AttemptWave
    valid: bool
    invalid_reason: str | None
    wall_seconds: float | None = Field(default=None, ge=0)
    # Runtime telemetry copied from usage when the runtime reported it; never affects validity.
    tool_calls: int | None = Field(default=None, ge=0)
    assistant_messages: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _derive_legacy_wave(cls, data: Any) -> Any:
        # Attempt records persisted before ``wave`` existed were built from the
        # initial dispatch followed by at most one retry, so the number is the wave.
        if isinstance(data, dict) and "wave" not in data and isinstance(data.get("attempt"), int):
            return {**data, "wave": "initial" if data["attempt"] == 1 else "retry"}
        return data

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
            waves = [attempt.wave for attempt in self.attempts]
            if waves != ["initial", *(["retry"] * (len(waves) - 1))]:
                raise ValueError(
                    "planned run attempts must be one initial wave followed only by retries"
                )
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
    coverage_redispatched: bool = False
    redispatch_skipped: RedispatchSkip | None = None
    redispatch: list[RunAttempt] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _aggregates_must_match_runs(self) -> LaneCoverage:
        identities = [(run.replica, run.chunk) for run in self.runs]
        if len(identities) != len(set(identities)):
            raise ValueError("coverage run identities must be unique")
        if self.redispatch_skipped is not None and self.coverage_redispatched:
            raise ValueError("a lane cannot be both coverage-redispatched and skipped")
        if self.redispatch:
            if not self.coverage_redispatched:
                raise ValueError("redispatch attempts require coverage_redispatched")
            if [attempt.attempt for attempt in self.redispatch] != list(
                range(1, len(self.redispatch) + 1)
            ):
                raise ValueError("redispatch attempts must be numbered 1..N in order")
            if any(attempt.wave != "coverage_redispatch" for attempt in self.redispatch):
                raise ValueError("redispatch attempts must belong to the coverage_redispatch wave")
        if self.dispatched != len(self.runs):
            raise ValueError("dispatched must equal the number of coverage runs")
        if self.valid != sum(run.valid for run in self.runs):
            raise ValueError("valid must equal the number of valid coverage runs")
        planned_findings = sum(run.findings for run in self.runs)
        if self.coverage_redispatched:
            if self.findings < planned_findings:
                raise ValueError("findings cannot be below the planned run finding total")
        elif self.findings != planned_findings:
            raise ValueError("findings must equal the coverage run finding total")
        return self


@dataclass(frozen=True)
class DiscoverResult:
    lane_results: dict[str, list[RunResult]]
    findings: list[EnrichedFinding]
    coverage: list[LaneCoverage]
    budget: DiffBudgetReport | None = None


def covered_hunk_ids(hunks: Sequence[Hunk], receipts: Sequence[str]) -> set[str]:
    """Map agent receipts to canonical controller hunk IDs."""

    by_file: dict[str, list[Hunk]] = {}
    for hunk in hunks:
        by_file.setdefault(hunk.file, []).append(hunk)
    covered: set[str] = set()
    for receipt in receipts:
        if receipt in by_file:
            covered.update(hunk.hunk_id for hunk in by_file[receipt])
            continue
        match = _COVERED_RANGE.fullmatch(receipt)
        if match is None:
            continue
        start = int(match.group("start"))
        end = int(match.group("end") or match.group("start"))
        if end < start:
            continue
        for hunk in by_file.get(match.group("file"), []):
            if hunk.new_count == 0:
                continue
            hunk_end = hunk.new_start + hunk.new_count - 1
            if start <= hunk_end and end >= hunk.new_start:
                covered.add(hunk.hunk_id)
    return covered


def _uncovered_for_lane(hunks: Sequence[Hunk], results: Sequence[RunResult]) -> list[str]:
    receipts = [
        receipt
        for result in results
        if result.status is RunStatus.VALID and result.output is not None
        for receipt in result.output.covered
    ]
    covered = covered_hunk_ids(hunks, receipts)
    return [hunk.hunk_id for hunk in hunks if hunk.hunk_id not in covered]


def dead_by_timeout(results: Sequence[RunResult]) -> bool:
    """True when every final planned execution of a lane died at the runtime deadline.

    ``results`` are the final results after the ordinary invalid-result retry, so an
    execution whose earlier attempt failed for another reason still counts as dead
    when its final attempt was the deadline kill. A lane with zero planned results
    is not dead; it simply has nothing to redispatch.
    """

    return bool(results) and all(
        result.status is RunStatus.INVALID and result.invalid_reason == DEAD_BY_TIMEOUT_REASON
        for result in results
    )


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
    registry: Registry | EffectiveRegistry,
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


def _run_attempt(attempt: int, wave: AttemptWave, result: RunResult) -> RunAttempt:
    usage = result.usage
    return RunAttempt(
        attempt=attempt,
        wave=wave,
        valid=result.status is RunStatus.VALID,
        invalid_reason=result.invalid_reason,
        wall_seconds=result.wall_seconds,
        tool_calls=usage.tool_calls if usage is not None else None,
        assistant_messages=usage.assistant_messages if usage is not None else None,
    )


def _coverage_attempts(
    result: RunResult,
    initial_by_key: Mapping[tuple[str, int, int], RunResult],
) -> list[RunAttempt]:
    initial = initial_by_key.get((result.lane_id, result.replica, result.chunk))
    if initial is None:
        return [_run_attempt(1, "initial", result)]
    return [_run_attempt(1, "initial", initial), _run_attempt(2, "retry", result)]


def _redispatch_attempts(results: Sequence[RunResult]) -> list[RunAttempt]:
    ordered = sorted(results, key=lambda result: (result.chunk, result.replica))
    return [
        _run_attempt(attempt, "coverage_redispatch", result)
        for attempt, result in enumerate(ordered, start=1)
    ]


async def discover(
    *,
    registry: Registry | EffectiveRegistry,
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
    mode: DiscoveryMode = DiscoveryMode.AGENTIC,
    repo_dir: Path | None = None,
    locale: Literal["ko", "en"] = "en",
) -> DiscoverResult:
    """Run all activated lanes in one dispatch call and enrich valid findings."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")

    owners = _active_lane_owners(registry, target, lane_filter)
    if isinstance(registry, EffectiveRegistry):
        lanes = [registry.load_lane(lane_id) for lane_id, _tier in owners]
    else:
        lanes = [
            load_lane(resolve_lane_path(lanes_root, lane_id, tier)) for lane_id, tier in owners
        ]
    covered_rules = {lane.id: lane.rules for lane in lanes}
    budget: DiffBudgetReport | None
    if mode is DiscoveryMode.INLINE:
        effective_brief, effective_brief_source = _effective_brief(target, brief, brief_source)
        chunks, budget = apply_diff_budget(target.diff)
        require_reviewable_diff(budget, source="target")
        planned_runs = [
            PlannedRun(
                lane=lane,
                prompt=build_lane_prompt(
                    lane,
                    diff=chunk.text,
                    brief=effective_brief,
                    brief_source=effective_brief_source,
                    covered_rules=covered_rules,
                    locale=locale,
                    deadline_seconds=deadline_seconds,
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
            for chunk in chunks
            for replica in range(1, replicas + 1)
        ]
    else:
        if target.base_sha is None:
            raise CheckoutVerificationError(
                "missing-base", "agentic discovery requires a target base SHA"
            )
        if repo_dir is None:
            raise CheckoutVerificationError(
                "missing-checkout", "agentic discovery requires a verified checkout"
            )
        budget = None
        planned_runs = [
            PlannedRun(
                lane=lane,
                prompt=build_agentic_lane_prompt(
                    lane,
                    base_sha=target.base_sha,
                    head_sha=target.head_sha,
                    locale=locale,
                    deadline_seconds=deadline_seconds,
                ),
                replica=replica,
                workdir=repo_dir,
            )
            for lane in lanes
            for replica in range(1, replicas + 1)
        ]
    dispatched = await dispatch_outcome(
        planned_runs,
        runtime,
        out_root=out_root,
        concurrency=concurrency,
        deadline_seconds=deadline_seconds,
        host_gate=host_gate,
    )
    raw_results = dispatched.results

    hunks = parse_hunks(target.diff)
    coverage_results: list[RunResult] = []
    redispatched_lanes: set[str] = set()
    redispatch_skipped: dict[str, RedispatchSkip] = {}
    if mode is DiscoveryMode.AGENTIC:
        for lane in lanes:
            lane_final = [result for result in raw_results if result.lane_id == lane.id]
            if not _uncovered_for_lane(hunks, lane_final):
                continue
            if dead_by_timeout(lane_final):
                # Re-running the same prompt under the same deadline is deterministic
                # waste (a guaranteed third full-deadline barrier); record, do not dispatch.
                redispatch_skipped[lane.id] = "dead_by_timeout"
                continue
            redispatch_runs = [
                run for run in planned_runs if run.lane.id == lane.id and run.replica == 1
            ]
            if redispatch_runs:
                redispatched_lanes.add(lane.id)
        redispatch_plan = [
            run for run in planned_runs if run.lane.id in redispatched_lanes and run.replica == 1
        ]
        if redispatch_plan:
            coverage_dispatch = await dispatch_outcome(
                redispatch_plan,
                runtime,
                out_root=out_root / "coverage-redispatch",
                concurrency=concurrency,
                deadline_seconds=deadline_seconds,
                host_gate=host_gate,
                retry_invalid=False,
            )
            coverage_results = coverage_dispatch.results

    lane_results: dict[str, list[RunResult]] = {lane.id: [] for lane in lanes}
    for result in [*raw_results, *coverage_results]:
        lane_results[result.lane_id].append(result)

    enriched: list[EnrichedFinding] = []
    finding_counts: dict[tuple[str, int, int], int] = {}
    coverage_finding_counts: dict[str, int] = {}
    for is_coverage_wave, result in [
        *((False, result) for result in raw_results),
        *((True, result) for result in coverage_results),
    ]:
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
            if is_coverage_wave:
                coverage_finding_counts[result.lane_id] = (
                    coverage_finding_counts.get(result.lane_id, 0) + 1
                )
            else:
                key = (result.lane_id, result.replica, result.chunk)
                finding_counts[key] = finding_counts.get(key, 0) + 1

    coverage: list[LaneCoverage] = []
    for lane in lanes:
        results = [result for result in raw_results if result.lane_id == lane.id]
        valid = sum(result.status is RunStatus.VALID for result in results)
        runs = [
            RunCoverage(
                replica=result.replica,
                chunk=result.chunk,
                valid=result.status is RunStatus.VALID,
                findings=finding_counts.get((result.lane_id, result.replica, result.chunk), 0),
                invalid_reason=result.invalid_reason,
                attempts=_coverage_attempts(result, dispatched.initial_by_key),
                diagnostic=result.diagnostic,
            )
            for result in results
        ]
        coverage.append(
            LaneCoverage(
                lane_id=lane.id,
                dispatched=len(runs),
                valid=valid,
                findings=sum(run.findings for run in runs)
                + coverage_finding_counts.get(lane.id, 0),
                runs=runs,
                coverage_redispatched=lane.id in redispatched_lanes,
                redispatch_skipped=redispatch_skipped.get(lane.id),
                redispatch=_redispatch_attempts(
                    [result for result in coverage_results if result.lane_id == lane.id]
                ),
                uncovered=(
                    _uncovered_for_lane(hunks, lane_results[lane.id])
                    if mode is DiscoveryMode.AGENTIC
                    else []
                ),
            )
        )

    return DiscoverResult(
        lane_results=lane_results,
        findings=enriched,
        coverage=coverage,
        budget=budget,
    )


__all__: list[str] = [
    "DEAD_BY_TIMEOUT_REASON",
    "AttemptWave",
    "DiscoverResult",
    "DiscoveryMode",
    "EnrichedFinding",
    "LaneCoverage",
    "RedispatchSkip",
    "RunAttempt",
    "RunCoverage",
    "covered_hunk_ids",
    "dead_by_timeout",
    "discover",
    "resolve_lane_path",
]
