"""File-backed artifacts for one rvw pipeline run."""

from __future__ import annotations

import errno
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage
from rvw.merge import MergeResult
from rvw.schema import Verdict
from rvw.target import ResolvedTarget

if TYPE_CHECKING:
    from rvw.gate import GateVerdict


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RUN_DIRECTORY_COLLISION_RETRIES = 3
_RUN_TIMESTAMP_REGENERATION_SPINS = 1000


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
        super().__init__(f"{stage.upper()} stage is missing from {run_dir}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        f"{json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


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
        _write_json(
            self.dir / "outcome.json",
            {
                "verdicts": {key: verdict.value for key, verdict in outcome.verdicts.items()},
                "reasons": outcome.reasons,
                "evidence": outcome.evidence,
                "replica_votes": {
                    key: [verdict.value for verdict in votes]
                    for key, votes in outcome.replica_votes.items()
                },
                "unresolved": outcome.unresolved,
                "coerced_rejections": outcome.coerced_rejections,
            },
        )

    def load_outcome(self) -> AdjudicationOutcome:
        raw = _load_json(self.dir / "outcome.json", "outcome")
        return AdjudicationOutcome(
            verdicts={key: Verdict(value) for key, value in raw["verdicts"].items()},
            reasons=raw["reasons"],
            evidence=raw["evidence"],
            replica_votes={
                key: [Verdict(value) for value in votes]
                for key, votes in raw["replica_votes"].items()
            },
            unresolved=raw["unresolved"],
            coerced_rejections=raw["coerced_rejections"],
        )

    def save_report(self, report: str) -> None:
        (self.dir / "report.md").write_text(report, encoding="utf-8")

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
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        for _attempt in range(_RUN_DIRECTORY_COLLISION_RETRIES):
            run_id = f"rvw-{timestamp}-{kind}-{short}"
            run_dir = self.root / run_id
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                previous_timestamp = timestamp
                for _ in range(_RUN_TIMESTAMP_REGENERATION_SPINS):
                    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
                    if timestamp != previous_timestamp:
                        break
                continue
            return RunHandle(run_id=run_id, dir=run_dir)
        run_id = f"rvw-{timestamp}-{kind}-{short}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return RunHandle(run_id=run_id, dir=run_dir)

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
