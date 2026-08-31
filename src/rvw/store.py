"""File-backed artifacts for one rvw pipeline run."""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport, DiffChunk
from rvw.discover import (
    INTERRUPTED_ATTEMPT_REASON,
    DiscoverResult,
    DiscoveryPlan,
    EnrichedFinding,
    LaneCoverage,
)
from rvw.discovery_cost import validate_discovery_preflight_payload
from rvw.dispatch import PlannedRun
from rvw.lane import Lane
from rvw.merge import MergeResult
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus
from rvw.schema import RuntimeLaneOutput
from rvw.summary import ReviewStatus, RunSummary, running_summary, summarize_run
from rvw.target import ResolvedTarget

if TYPE_CHECKING:
    from rvw.gate import GateVerdict


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RUN_DIRECTORY_COLLISION_RETRIES = 3
_RUN_TIMESTAMP_REGENERATION_SPINS = 1000

# Canonical run-ID grammar. `create()` below is the generator; parsing helpers
# stay next to it so discovery-side consumers cannot drift from the generated
# shape (they previously re-declared the regex and strptime format).
# Generated timestamps carry microseconds (concurrent-run safety, #16); the
# parser also accepts the pre-#16 second-resolution shape so runs recorded
# before an upgrade remain discoverable for inheritance.
_RUN_ID_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
_PR_RUN_ID = re.compile(
    r"^rvw-(?P<timestamp>\d{8}-\d{6})(?:-(?P<micro>\d{6}))?-pr-(?P<pr_number>\d+)$"
)


def parse_pr_run_id(run_id: str) -> tuple[datetime, int] | None:
    """Parse a canonical PR run ID into (timestamp, pr_number), or None.

    Full-match only: arbitrary suffixes after the canonical shape do not
    qualify, so hostile directory names planted in a writable artifact root
    cannot reach discovery output or provenance sinks.
    """

    match = _PR_RUN_ID.fullmatch(run_id)
    if match is None:
        return None
    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    micro = match.group("micro")
    if micro is not None:
        timestamp = timestamp.replace(microsecond=int(micro))
    return timestamp, int(match.group("pr_number"))


class RunNotFound(FileNotFoundError):
    """The requested run directory does not exist."""

    def __init__(self, run_id: str, root: Path) -> None:
        self.run_id = run_id
        self.root = root
        super().__init__(f"run not found: {run_id} under {root}")


class InvalidRunId(ValueError):
    """A run identifier is not a safe direct child of the artifact root."""

    def __init__(self, run_id: str, root: Path) -> None:
        self.run_id = run_id
        self.root = root
        super().__init__(f"invalid run ID: {run_id!r} under {root}")


class StageMissing(FileNotFoundError):
    """A run exists, but an expected stage artifact does not."""

    def __init__(self, stage: str, run_dir: Path) -> None:
        self.stage = stage
        self.run_dir = run_dir
        suffix = ".md" if stage == "report" else ".json"
        super().__init__(
            f"{stage.upper()} stage is missing required artifact {stage}{suffix} from {run_dir}"
        )


class _StoredPlannedRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    prompt: str
    replica: int = Field(ge=1)
    chunk: int = Field(ge=1)
    chunk_count: int = Field(ge=1)


class _StoredDiscoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lanes: list[Lane]
    chunks: list[DiffChunk]
    budget: DiffBudgetReport
    runs: list[_StoredPlannedRun]
    skipped_lane_ids: list[str]
    replicas: int = Field(ge=1)

    @classmethod
    def from_plan(cls, plan: DiscoveryPlan) -> _StoredDiscoveryPlan:
        return cls(
            lanes=plan.lanes,
            chunks=plan.chunks,
            budget=plan.budget,
            runs=[
                _StoredPlannedRun(
                    lane_id=run.lane.id,
                    prompt=run.prompt,
                    replica=run.replica,
                    chunk=run.chunk,
                    chunk_count=run.chunk_count,
                )
                for run in plan.runs
            ],
            skipped_lane_ids=sorted(plan.skipped_lane_ids),
            replicas=plan.replicas,
        )

    def to_plan(self) -> DiscoveryPlan:
        lanes_by_id = {lane.id: lane for lane in self.lanes}
        if len(lanes_by_id) != len(self.lanes):
            raise ValueError("discovery plan contains duplicate lane IDs")
        try:
            runs = [
                PlannedRun(
                    lane=lanes_by_id[run.lane_id],
                    prompt=run.prompt,
                    replica=run.replica,
                    chunk=run.chunk,
                    chunk_count=run.chunk_count,
                )
                for run in self.runs
            ]
        except KeyError as exc:
            raise ValueError("discovery plan run references an unknown lane") from exc
        return DiscoveryPlan(
            lanes=self.lanes,
            chunks=self.chunks,
            budget=self.budget,
            runs=runs,
            skipped_lane_ids=set(self.skipped_lane_ids),
            replicas=self.replicas,
        )


class _StoredDiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    replica: int = Field(ge=1)
    chunk: int = Field(ge=1)
    status: RunStatus
    output: RuntimeLaneOutput | None
    invalid_reason: str | None
    wall_seconds: float = Field(ge=0)
    artifact_dir: Path
    diagnostic: RunDiagnostic | None = None

    @classmethod
    def from_result(cls, result: RunResult[RuntimeLaneOutput]) -> _StoredDiscoveryResult:
        return cls(
            lane_id=result.lane_id,
            replica=result.replica,
            chunk=result.chunk,
            status=result.status,
            output=result.output,
            invalid_reason=result.invalid_reason,
            wall_seconds=result.wall_seconds,
            artifact_dir=result.artifact_dir,
            diagnostic=result.diagnostic,
        )

    def to_result(self) -> RunResult[RuntimeLaneOutput]:
        return RunResult(
            lane_id=self.lane_id,
            replica=self.replica,
            chunk=self.chunk,
            status=self.status,
            output=self.output,
            invalid_reason=self.invalid_reason,
            wall_seconds=self.wall_seconds,
            artifact_dir=self.artifact_dir,
            diagnostic=self.diagnostic,
        )


class _StoredDiscoveryAttempt(BaseModel):
    """Durable start marker and optional completion for one runtime call."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    replica: int = Field(ge=1)
    chunk: int = Field(ge=1)
    attempt: int = Field(ge=1)
    artifact_dir: Path
    result: _StoredDiscoveryResult | None = None

    @model_validator(mode="after")
    def _result_must_match_started_identity(self) -> _StoredDiscoveryAttempt:
        if self.result is not None and (
            self.result.lane_id != self.lane_id
            or self.result.replica != self.replica
            or self.result.chunk != self.chunk
            or self.result.artifact_dir != self.artifact_dir
        ):
            raise ValueError("discovery attempt result must match its started identity")
        return self


class _DiscoveryProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: list[_StoredDiscoveryAttempt] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_completed_results(cls, value: Any) -> Any:
        """Load the prior completed-result-only artifact as completed attempts."""

        if not isinstance(value, dict) or "attempts" in value or "results" not in value:
            return value
        migrated = dict(value)
        counts: dict[tuple[str, int, int], int] = {}
        attempts: list[dict[str, Any]] = []
        for result in migrated.pop("results"):
            key = (result["lane_id"], result["replica"], result["chunk"])
            attempt = counts.get(key, 0) + 1
            counts[key] = attempt
            attempts.append(
                {
                    "lane_id": key[0],
                    "replica": key[1],
                    "chunk": key[2],
                    "attempt": attempt,
                    "artifact_dir": result["artifact_dir"],
                    "result": result,
                }
            )
        migrated["attempts"] = attempts
        return migrated

    @model_validator(mode="after")
    def _attempts_are_bounded_and_ordered(self) -> _DiscoveryProgress:
        histories: dict[tuple[str, int, int], list[_StoredDiscoveryAttempt]] = {}
        for attempt in self.attempts:
            histories.setdefault((attempt.lane_id, attempt.replica, attempt.chunk), []).append(
                attempt
            )
        for history in histories.values():
            if len(history) > 2:
                raise ValueError("discovery progress cannot contain more than two attempts")
            if [attempt.attempt for attempt in history] != list(range(1, len(history) + 1)):
                raise ValueError("discovery attempt numbers must be ordered from one")
            if (
                len(history) == 2
                and history[0].result is not None
                and history[0].result.status is RunStatus.VALID
            ):
                raise ValueError("valid discovery results cannot have a replacement attempt")
            if any(attempt.result is None for attempt in history[:-1]):
                raise ValueError("only the latest discovery attempt may be incomplete")
        return self


def _interrupted_result(attempt: _StoredDiscoveryAttempt) -> _StoredDiscoveryResult:
    return _StoredDiscoveryResult(
        lane_id=attempt.lane_id,
        replica=attempt.replica,
        chunk=attempt.chunk,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason=INTERRUPTED_ATTEMPT_REASON,
        wall_seconds=0,
        artifact_dir=attempt.artifact_dir,
    )


class _ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discover_replicas: int = Field(ge=1)
    adjudicate_replicas: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    deadline_seconds: int = Field(ge=1)
    max_discovery_runs: int = Field(ge=1)


def _write_json(path: Path, value: object) -> None:
    text = f"{json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as artifact:
            artifact.write(text)
            artifact.flush()
            os.fsync(artifact.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_json(path: Path, stage: str) -> Any:
    if not path.is_file():
        raise StageMissing(stage, path.parent)
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class RunHandle:
    """Paths and typed stage persistence for one run."""

    run_id: str
    dir: Path
    _dir_fd: int | None = field(default=None, repr=False, compare=False)

    def _pinned_dir_fd(self) -> int:
        fd = self._dir_fd
        if fd is not None:
            return fd
        try:
            fd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise InvalidRunId(self.run_id, self.dir.parent) from exc
            raise
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            os.close(fd)
            raise InvalidRunId(self.run_id, self.dir.parent)
        object.__setattr__(self, "_dir_fd", fd)
        return fd

    def close(self) -> None:
        fd = self._dir_fd
        if fd is not None:
            os.close(fd)
            object.__setattr__(self, "_dir_fd", None)

    def __enter__(self) -> RunHandle:
        self._pinned_dir_fd()
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.close()

    def __del__(self) -> None:
        self.close()

    def _load_contained_json(self, name: str, stage: str) -> Any:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=self._pinned_dir_fd(),
            )
        except FileNotFoundError as exc:
            raise StageMissing(stage, self.dir) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise InvalidRunId(self.run_id, self.dir.parent) from exc
            raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise InvalidRunId(self.run_id, self.dir.parent)
            with os.fdopen(fd, encoding="utf-8") as artifact:
                fd = -1
                return json.load(artifact)
        finally:
            if fd >= 0:
                os.close(fd)

    def _load_contained_text(self, name: str, stage: str) -> str:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=self._pinned_dir_fd(),
            )
        except FileNotFoundError as exc:
            raise StageMissing(stage, self.dir) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise InvalidRunId(self.run_id, self.dir.parent) from exc
            raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise InvalidRunId(self.run_id, self.dir.parent)
            with os.fdopen(fd, encoding="utf-8") as artifact:
                fd = -1
                return artifact.read()
        finally:
            if fd >= 0:
                os.close(fd)

    def save_target(self, target: ResolvedTarget) -> None:
        _write_json(self.dir / "target.json", target.model_dump(mode="json"))

    def load_target(self) -> ResolvedTarget:
        return ResolvedTarget.model_validate(self._load_contained_json("target.json", "target"))

    def save_summary(self, summary: RunSummary) -> None:
        _write_json(self.dir / "run.json", summary.model_dump(mode="json"))

    def load_summary(self) -> RunSummary:
        raw = self._load_contained_json("run.json", "run")
        summary = RunSummary.model_validate(raw)
        if not isinstance(raw, dict) or "skipped_lanes" in raw:
            return summary
        try:
            discovered = self.load_discover()
        except StageMissing:
            if summary.status is ReviewStatus.COMPLETE:
                return summary.model_copy(update={"status": ReviewStatus.DEGRADED})
            return summary
        if summary.status is ReviewStatus.RUNNING:
            return summary
        recomputed = summarize_run(
            summary.run_id,
            discovered,
            error=summary.error,
            build=summary.build,
        )
        status_rank = {
            ReviewStatus.COMPLETE: 0,
            ReviewStatus.DEGRADED: 1,
            ReviewStatus.FAILED: 2,
        }
        if status_rank[summary.status] >= status_rank[recomputed.status]:
            return recomputed.model_copy(update={"status": summary.status})
        return recomputed

    def save_preflight(self, preflight: dict[str, object]) -> None:
        _write_json(self.dir / "preflight.json", validate_discovery_preflight_payload(preflight))

    def load_preflight(self) -> dict[str, object]:
        raw = self._load_contained_json("preflight.json", "preflight")
        return validate_discovery_preflight_payload(raw)

    def save_discovery_plan(self, plan: DiscoveryPlan) -> None:
        _write_json(
            self.dir / "discovery-plan.json",
            _StoredDiscoveryPlan.from_plan(plan).model_dump(mode="json", by_alias=True),
        )

    def load_discovery_plan(self) -> DiscoveryPlan:
        raw = self._load_contained_json("discovery-plan.json", "discovery-plan")
        return _StoredDiscoveryPlan.model_validate(raw).to_plan()

    def save_execution_config(
        self,
        *,
        discover_replicas: int,
        adjudicate_replicas: int,
        concurrency: int,
        deadline_seconds: int,
        max_discovery_runs: int,
    ) -> None:
        config = _ExecutionConfig(
            discover_replicas=discover_replicas,
            adjudicate_replicas=adjudicate_replicas,
            concurrency=concurrency,
            deadline_seconds=deadline_seconds,
            max_discovery_runs=max_discovery_runs,
        )
        _write_json(self.dir / "execution.json", config.model_dump(mode="json"))

    def load_execution_config(self) -> dict[str, int]:
        raw = self._load_contained_json("execution.json", "execution")
        return _ExecutionConfig.model_validate(raw).model_dump()

    def _load_discovery_progress_artifact(self) -> _DiscoveryProgress:
        try:
            raw = self._load_contained_json("discovery-progress.json", "discovery-progress")
        except StageMissing:
            return _DiscoveryProgress()
        return _DiscoveryProgress.model_validate(raw)

    def append_discovery_attempt_started(
        self,
        lane_id: str,
        replica: int,
        chunk: int,
        attempt: int,
        artifact_dir: Path,
    ) -> None:
        progress = self._load_discovery_progress_artifact()
        key = (lane_id, replica, chunk)
        history = [
            item for item in progress.attempts if (item.lane_id, item.replica, item.chunk) == key
        ]
        if attempt != len(history) + 1:
            raise ValueError("discovery attempt start must use the next attempt number")
        attempts = list(progress.attempts)
        if history and history[-1].result is None:
            previous = history[-1]
            previous_index = attempts.index(previous)
            attempts[previous_index] = previous.model_copy(
                update={"result": _interrupted_result(previous)}
            )
        updated = _DiscoveryProgress(
            attempts=[
                *attempts,
                _StoredDiscoveryAttempt(
                    lane_id=lane_id,
                    replica=replica,
                    chunk=chunk,
                    attempt=attempt,
                    artifact_dir=artifact_dir,
                ),
            ]
        )
        _write_json(self.dir / "discovery-progress.json", updated.model_dump(mode="json"))

    def finalize_incomplete_discovery_attempts(self) -> set[tuple[str, int, int]]:
        """Persist started attempts left without a runtime result as interrupted."""

        progress = self._load_discovery_progress_artifact()
        incomplete_keys = {
            (attempt.lane_id, attempt.replica, attempt.chunk)
            for attempt in progress.attempts
            if attempt.result is None
        }
        if not incomplete_keys:
            return set()
        updated = _DiscoveryProgress(
            attempts=[
                attempt
                if attempt.result is not None
                else attempt.model_copy(update={"result": _interrupted_result(attempt)})
                for attempt in progress.attempts
            ]
        )
        _write_json(self.dir / "discovery-progress.json", updated.model_dump(mode="json"))
        return incomplete_keys

    def append_discovery_progress(self, result: RunResult[RuntimeLaneOutput]) -> None:
        progress = self._load_discovery_progress_artifact()
        stored_result = _StoredDiscoveryResult.from_result(result)
        matching_indices = [
            index
            for index, attempt in enumerate(progress.attempts)
            if (
                attempt.lane_id,
                attempt.replica,
                attempt.chunk,
                attempt.artifact_dir,
            )
            == (result.lane_id, result.replica, result.chunk, result.artifact_dir)
        ]
        if matching_indices:
            if len(matching_indices) != 1:
                raise ValueError("discovery attempt completion is ambiguous")
            index = matching_indices[0]
            existing = progress.attempts[index]
            if existing.result is not None:
                if existing.result == stored_result:
                    return
                raise ValueError("discovery attempt already has a different result")
            attempts = list(progress.attempts)
            attempts[index] = existing.model_copy(update={"result": stored_result})
            updated = _DiscoveryProgress(attempts=attempts)
        else:
            key = (result.lane_id, result.replica, result.chunk)
            history = [
                attempt
                for attempt in progress.attempts
                if (attempt.lane_id, attempt.replica, attempt.chunk) == key
            ]
            updated = _DiscoveryProgress(
                attempts=[
                    *progress.attempts,
                    _StoredDiscoveryAttempt(
                        lane_id=result.lane_id,
                        replica=result.replica,
                        chunk=result.chunk,
                        attempt=len(history) + 1,
                        artifact_dir=result.artifact_dir,
                        result=stored_result,
                    ),
                ]
            )
        _write_json(self.dir / "discovery-progress.json", updated.model_dump(mode="json"))

    def load_discovery_progress(
        self,
    ) -> dict[tuple[str, int, int], list[RunResult[RuntimeLaneOutput]]]:
        raw = self._load_contained_json("discovery-progress.json", "discovery-progress")
        progress = _DiscoveryProgress.model_validate(raw)
        histories: dict[tuple[str, int, int], list[RunResult[RuntimeLaneOutput]]] = {}
        for attempt in progress.attempts:
            result = (
                attempt.result.to_result()
                if attempt.result is not None
                else RunResult(
                    lane_id=attempt.lane_id,
                    replica=attempt.replica,
                    chunk=attempt.chunk,
                    status=RunStatus.INVALID,
                    output=None,
                    invalid_reason=INTERRUPTED_ATTEMPT_REASON,
                    wall_seconds=0,
                    artifact_dir=attempt.artifact_dir,
                )
            )
            histories.setdefault((result.lane_id, result.replica, result.chunk), []).append(result)
        return histories

    def load_incomplete_discovery_attempts(self) -> set[tuple[str, int, int]]:
        raw = self._load_contained_json("discovery-progress.json", "discovery-progress")
        progress = _DiscoveryProgress.model_validate(raw)
        return {
            (attempt.lane_id, attempt.replica, attempt.chunk)
            for attempt in progress.attempts
            if attempt.result is None
        }

    def save_discover(self, discovered: DiscoverResult) -> None:
        _write_json(
            self.dir / "discover.json",
            {
                "findings": [finding.model_dump(mode="json") for finding in discovered.findings],
                "coverage": [item.model_dump(mode="json") for item in discovered.coverage],
                "budget": (
                    discovered.budget.model_dump(mode="json")
                    if discovered.budget is not None
                    else None
                ),
            },
        )

    def load_discover(self) -> DiscoverResult:
        raw = _load_json(self.dir / "discover.json", "discover")
        budget_raw = raw["budget"]
        return DiscoverResult(
            lane_results={},
            findings=[EnrichedFinding.model_validate(item) for item in raw["findings"]],
            coverage=[LaneCoverage.model_validate(item) for item in raw["coverage"]],
            budget=(
                DiffBudgetReport.model_validate(budget_raw) if budget_raw is not None else None
            ),
        )

    def save_merge(self, merged: MergeResult) -> None:
        _write_json(self.dir / "merge.json", merged.model_dump(mode="json"))

    def load_merge(self) -> MergeResult:
        return MergeResult.model_validate(_load_json(self.dir / "merge.json", "merge"))

    def save_outcome(self, outcome: AdjudicationOutcome) -> None:
        _write_json(self.dir / "outcome.json", outcome.model_dump(mode="json"))

    def load_outcome(self) -> AdjudicationOutcome:
        raw = _load_json(self.dir / "outcome.json", "outcome")
        return AdjudicationOutcome.model_validate(raw)

    def save_report(self, report: str) -> None:
        path = self.dir / "report.md"
        fd, temporary_name = tempfile.mkstemp(prefix=".report.md.", dir=self.dir)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as artifact:
                artifact.write(report)
                artifact.flush()
                os.fsync(artifact.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def load_report(self) -> str:
        path = self.dir / "report.md"
        if not path.is_file():
            raise StageMissing("report", self.dir)
        return path.read_text(encoding="utf-8")

    def load_gate_verdict(self) -> GateVerdict:
        from rvw.gate import GateVerdict

        return GateVerdict.model_validate(
            self._load_contained_json("gate-verdict.json", "gate-verdict")
        )


class RunStore:
    """Create and reopen run directories beneath one artifact root."""

    def __init__(self, root: Path = Path("/tmp/rvw")) -> None:
        self.root = root

    def create(self, target: ResolvedTarget) -> RunHandle:
        if target.kind == "pr":
            kind = "pr"
            short = str(target.pr_number)
        elif target.kind == "commit":
            kind = "commit"
            short = target.head_sha[:9]
        else:
            kind = "wt"
            short = "dirty"
        timestamp = datetime.now(UTC).strftime(_RUN_ID_TIMESTAMP_FORMAT)
        for _attempt in range(_RUN_DIRECTORY_COLLISION_RETRIES):
            run_id = f"rvw-{timestamp}-{kind}-{short}"
            run_dir = self.root / run_id
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                previous_timestamp = timestamp
                for _ in range(_RUN_TIMESTAMP_REGENERATION_SPINS):
                    timestamp = datetime.now(UTC).strftime(_RUN_ID_TIMESTAMP_FORMAT)
                    if timestamp != previous_timestamp:
                        break
                continue
            run = RunHandle(run_id=run_id, dir=run_dir)
            run.save_summary(running_summary(run_id))
            return run
        run_id = f"rvw-{timestamp}-{kind}-{short}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        run = RunHandle(run_id=run_id, dir=run_dir)
        run.save_summary(running_summary(run_id))
        return run

    def open(self, run_id: str) -> RunHandle:
        if not _SAFE_RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
            raise InvalidRunId(run_id, self.root)
        run_dir = self.root / run_id
        if run_dir.is_symlink():
            raise InvalidRunId(run_id, self.root)
        resolved_root = self.root.resolve()
        resolved_run = run_dir.resolve()
        if not resolved_run.is_relative_to(resolved_root) or resolved_run == resolved_root:
            raise InvalidRunId(run_id, self.root)
        try:
            fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError as exc:
            raise RunNotFound(run_id, self.root) from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise InvalidRunId(run_id, self.root) from exc
            raise
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            os.close(fd)
            raise InvalidRunId(run_id, self.root)
        return RunHandle(run_id=run_id, dir=run_dir, _dir_fd=fd)


__all__ = ["InvalidRunId", "RunHandle", "RunNotFound", "RunStore", "StageMissing"]
