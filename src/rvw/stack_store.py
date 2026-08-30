"""Strict file-backed artifacts for one stacked pull-request run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.discovery_cost import validate_discovery_preflight_payload
from rvw.stack import FindingLineage, MemberRunRef, StackManifest, verify_lineages


class StackRunNotFound(FileNotFoundError):
    def __init__(self, run_id: str, root: Path) -> None:
        self.run_id = run_id
        self.root = root
        super().__init__(f"stack run not found: {run_id} under {root}")


class StackStageMissing(FileNotFoundError):
    def __init__(self, stage: str, run_dir: Path) -> None:
        self.stage = stage
        self.run_dir = run_dir
        super().__init__(f"{stage.upper()} stack stage is missing or incomplete in {run_dir}")


class _MemberRunsArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    stack_run_id: str
    members: list[MemberRunRef]

    @model_validator(mode="after")
    def _members_are_unique(self) -> _MemberRunsArtifact:
        numbers = [member.pr_number for member in self.members]
        if len(numbers) != len(set(numbers)):
            raise ValueError("member run PR numbers must be unique")
        run_ids = [member.run_id for member in self.members]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("ordinary member run IDs must be unique")
        return self


class _LineageArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    stack_run_id: str
    lineages: list[FindingLineage]
    coerced_evidence: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _lineages_are_unique(self) -> _LineageArtifact:
        lineage_ids = [lineage.lineage_id for lineage in self.lineages]
        if len(lineage_ids) != len(set(lineage_ids)):
            raise ValueError("lineage IDs must be unique")
        return self


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        f"{json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def _read_text(path: Path, stage: str) -> str:
    if not path.is_file():
        raise StackStageMissing(stage, path.parent)
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class StackRunHandle:
    run_id: str
    dir: Path

    def save_manifest(self, manifest: StackManifest) -> None:
        if manifest.run_id != self.run_id:
            raise ValueError("manifest run ID does not match stack handle")
        _write_json(
            self.dir / "stack-manifest.json",
            manifest.model_dump(mode="json"),
        )

    def load_manifest(self) -> StackManifest:
        return StackManifest.model_validate_json(
            _read_text(self.dir / "stack-manifest.json", "manifest")
        )

    def save_preflight(self, preflight: dict[str, object]) -> None:
        _write_json(self.dir / "preflight.json", validate_discovery_preflight_payload(preflight))

    def load_preflight(self) -> dict[str, object]:
        return validate_discovery_preflight_payload(
            json.loads(_read_text(self.dir / "preflight.json", "preflight"))
        )

    def save_member_runs(self, members: list[MemberRunRef]) -> None:
        artifact = _MemberRunsArtifact(
            stack_run_id=self.run_id,
            members=members,
        )
        _write_json(
            self.dir / "member-runs.json",
            artifact.model_dump(mode="json"),
        )

    def load_member_runs(self) -> list[MemberRunRef]:
        artifact = _MemberRunsArtifact.model_validate_json(
            _read_text(self.dir / "member-runs.json", "member-runs")
        )
        if artifact.stack_run_id != self.run_id:
            raise ValueError("member-runs artifact belongs to another stack run")
        return artifact.members

    def save_lineages(
        self,
        lineages: list[FindingLineage],
        *,
        coerced_evidence: int = 0,
    ) -> None:
        artifact = _LineageArtifact(
            stack_run_id=self.run_id,
            lineages=lineages,
            coerced_evidence=coerced_evidence,
        )
        _write_json(
            self.dir / "lineage.json",
            artifact.model_dump(mode="json"),
        )

    def load_lineages(self) -> list[FindingLineage]:
        artifact = _LineageArtifact.model_validate_json(
            _read_text(self.dir / "lineage.json", "lineage")
        )
        if artifact.stack_run_id != self.run_id:
            raise ValueError("lineage artifact belongs to another stack run")
        return artifact.lineages

    def save_report(self, report: str) -> None:
        (self.dir / "stack-report.md").write_text(report, encoding="utf-8")

    def load_report(self) -> str:
        return _read_text(self.dir / "stack-report.md", "report")

    def require_complete(self) -> None:
        try:
            manifest = self.load_manifest()
            member_runs = self.load_member_runs()
            lineages = self.load_lineages()
            self.load_report()
        except StackStageMissing as exc:
            raise StackStageMissing("complete", self.dir) from exc
        expected = [member.number for member in manifest.members]
        actual = [member.pr_number for member in member_runs]
        if actual != expected:
            raise StackStageMissing("complete", self.dir)
        verify_lineages(manifest, lineages)


class StackStore:
    """Create and reopen stack run directories beneath one artifact root."""

    def __init__(self, root: Path = Path("/tmp/rvw")) -> None:
        self.root = root

    def create(self, pr_numbers: list[int]) -> StackRunHandle:
        if len(pr_numbers) < 2:
            raise ValueError("stack requires at least two pull requests")
        if len(pr_numbers) != len(set(pr_numbers)):
            raise ValueError("stack pull-request numbers must be unique")
        if any(number < 1 for number in pr_numbers):
            raise ValueError("stack pull-request numbers must be positive")
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        run_id = f"rvw-stack-{timestamp}-prs-{pr_numbers[0]}-{pr_numbers[-1]}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return StackRunHandle(run_id=run_id, dir=run_dir)

    def open(self, run_id: str) -> StackRunHandle:
        if Path(run_id).name != run_id or not run_id.startswith("rvw-stack-"):
            raise StackRunNotFound(run_id, self.root)
        run_dir = self.root / run_id
        if not run_dir.is_dir():
            raise StackRunNotFound(run_id, self.root)
        return StackRunHandle(run_id=run_id, dir=run_dir)


__all__ = [
    "StackRunHandle",
    "StackRunNotFound",
    "StackStageMissing",
    "StackStore",
]
