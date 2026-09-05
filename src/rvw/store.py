"""File-backed artifacts for one rvw pipeline run."""

from __future__ import annotations

import errno
import json
import os
import platform
import re
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rvw import __version__
from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage
from rvw.merge import MergeResult
from rvw.summary import (
    ArtifactEntry,
    ExecutionSummary,
    ProcessFailure,
    ProcessResult,
    ProcessTarget,
    RunSummary,
    RuntimeSettings,
    SDKObservations,
    running_summary,
)
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
        return RunSummary.model_validate(self._load_contained_json("run.json", "run"))

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


def save_process(out: Path, process: ProcessResult) -> None:
    """Atomically persist a self-inclusive manifest with exact byte sizes."""
    entries = [
        ArtifactEntry(path=path.relative_to(out).as_posix(), size_bytes=path.stat().st_size)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and path != out / "process.json"
        and not any((out / parent).is_symlink() for parent in path.relative_to(out).parents)
    ]
    # The decimal digit count of process.json's own size converges in a few passes.
    size = 0
    for _ in range(10):
        process.artifacts = sorted(
            [*entries, ArtifactEntry(path="process.json", size_bytes=size)],
            key=lambda item: item.path,
        )
        payload = ProcessResult.model_validate(process.model_dump()).model_dump(mode="json")
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        if len(encoded) == size:
            _write_json(out / "process.json", payload)
            return
        size = len(encoded)
    raise RuntimeError("process manifest size did not converge")


def redact_diagnostic(text: str) -> str:
    """Remove inherited credentials before persisting controller diagnostics."""
    for key, value in os.environ.items():
        if value and re.search(r"TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY", key, re.I):
            text = text.replace(value, "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer|token)\s+[^\s\"']+",
        r"\1[REDACTED]",
        text,
    )
    return text


@contextmanager
def diagnostic_attempt(name: str) -> Iterator[None]:
    """Keep terminal persistence independent without hiding failed attempts."""
    try:
        yield
    except OSError as exc:
        print(
            f"diagnostic persistence failed ({name}): {redact_diagnostic(str(exc))}",
            file=sys.stderr,
        )


def initialize_process(
    out: Path | None,
    *,
    target_spec: str,
    base_ref: str | None = None,
    head_ref: str | None = None,
    command: list[str] | None = None,
    runtime: RuntimeSettings | None = None,
    root: Path = Path("/tmp/rvw"),
) -> tuple[RunHandle, ProcessResult]:
    """Initialize partial diagnostics before target resolution or runtime work."""
    match = re.match(
        r"https?://github\.com/([^/\s]+/[^/\s]+)/pull/([0-9]+)(?:[/?#]|$)", target_spec
    )
    target = ProcessTarget(base=base_ref, head=head_ref)
    if match:
        target.repo = match[1]
        target.pr = int(match[2]) if int(match[2]) > 0 else None
    elif target_spec.isdecimal() and int(target_spec) > 0:
        target.pr = int(target_spec)
    suffix = f"pr-{target.pr}" if target.pr else "run-pending"
    run_id = f"rvw-{datetime.now(UTC).strftime(_RUN_ID_TIMESTAMP_FORMAT)}-{suffix}"
    if out is None:
        for _ in range(1000):
            out = root / run_id
            try:
                out.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                run_id = f"rvw-{datetime.now(UTC).strftime(_RUN_ID_TIMESTAMP_FORMAT)}-{suffix}"
        else:
            raise FileExistsError("could not allocate a unique run directory")
    else:
        out.mkdir(parents=True, exist_ok=True)
    process = ProcessResult(
        run_id=run_id,
        target=target,
        command=command or ["rvw", "run", "--target", target_spec],
        runtime=runtime or RuntimeSettings(),
        failure=ProcessFailure(code="execution_incomplete", detail="review has not completed"),
    )
    with diagnostic_attempt("run.log"):
        (out / "run.log").touch(exist_ok=True)
    # An allowlist records effective settings without dumping host secrets or endpoints.
    environment = f"rvw={__version__}\npython={platform.python_version()}\n"
    environment += "\n".join(
        f"{key}={value}" for key, value in process.runtime.model_dump().items()
    )
    with diagnostic_attempt("environment.txt"):
        (out / "environment.txt").write_text(environment + "\n", encoding="utf-8")
    with diagnostic_attempt("summary.json"):
        _write_json(out / "summary.json", ExecutionSummary().model_dump(mode="json"))
    run = RunHandle(run_id=run_id, dir=out)
    with diagnostic_attempt("run.json"):
        run.save_summary(running_summary(run_id))
    save_process(out, process)
    return run, process


def finalize_process(
    out: Path,
    *,
    failure_code: str | None = None,
    failure_detail: str | None = None,
    sdk_observations: SDKObservations | None = None,
) -> ProcessResult:
    """Complete diagnostics after an adapter observes a forced terminal path."""
    try:
        process = ProcessResult.model_validate_json((out / "process.json").read_text())
    except (OSError, ValueError):
        _, process = initialize_process(out, target_spec="unknown")
    if failure_code:
        process.status = "infra_failed"
        process.exit_code = 3
        process.failure = ProcessFailure(
            code=failure_code,
            detail=redact_diagnostic(failure_detail or failure_code),
        )
    if sdk_observations is not None:
        process.sdk_observations = SDKObservations.model_validate_json(
            redact_diagnostic(sdk_observations.model_dump_json())
        )
    with diagnostic_attempt("summary.json"):
        if not (out / "summary.json").is_file():
            _write_json(out / "summary.json", ExecutionSummary().model_dump(mode="json"))
    with diagnostic_attempt("environment.txt"):
        if not (out / "environment.txt").is_file():
            (out / "environment.txt").write_text(f"rvw={__version__}\n", encoding="utf-8")
    with diagnostic_attempt("run.log"), (out / "run.log").open("a", encoding="utf-8") as log:
        if process.failure:
            log.write(f"{process.failure.code}:{process.failure.detail}\n")
    for name in ("run.log", "environment.txt"):
        path = out / name
        with diagnostic_attempt(name):
            path.write_text(redact_diagnostic(path.read_text(encoding="utf-8")), encoding="utf-8")
    save_process(out, process)
    return process


def _contract_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Python-owned review diagnostic persistence")
    parser.add_argument("action", choices=["initialize", "finalize"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target", default="unknown")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--failure-code")
    parser.add_argument("--failure-detail")
    parser.add_argument("--sdk-observations-json")
    args = parser.parse_args()
    if args.action == "initialize":
        initialize_process(
            args.out, target_spec=args.target, base_ref=args.base_ref, head_ref=args.head_ref
        )
    else:
        finalize_process(
            args.out,
            failure_code=args.failure_code,
            failure_detail=args.failure_detail,
            sdk_observations=(
                SDKObservations.model_validate_json(args.sdk_observations_json)
                if args.sdk_observations_json
                else None
            ),
        )


if __name__ == "__main__":
    _contract_main()
