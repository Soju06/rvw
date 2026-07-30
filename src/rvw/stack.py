"""Explicit stacked pull-request models, resolution, and lineage transitions."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from collections.abc import Callable, Sequence
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rvw.adjudicate import AdjudicationOutcome
from rvw.merge import MergeResult
from rvw.schema import Severity, Verdict
from rvw.target import ResolvedTarget

CommandRunner = Callable[[list[str], Path], str]
_SHA_FIELD = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
_VERDICT_KEYS = {"CONFIRMED", "REJECTED", "UNCERTAIN"}


class StackInvariantError(ValueError):
    """A resolved or persisted stack violates the direct-chain contract."""


class StackResolutionError(RuntimeError):
    """A command required to resolve stack metadata or source failed."""

    def __init__(self, command: list[str], detail: str | None = None) -> None:
        self.command = command
        message = f"stack resolution command failed: {shlex.join(command)}"
        if detail:
            message = f"{message}: {detail.strip()}"
        super().__init__(message)


class StackMember(BaseModel):
    """One immutable pull-request member captured in caller order."""

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1)
    number: int = Field(ge=1)
    url: str = Field(min_length=1)
    title: str
    body: str | None = None
    state: str
    merged: bool
    base_ref: str = Field(min_length=1)
    base_sha: str = _SHA_FIELD
    head_ref: str = Field(min_length=1)
    head_sha: str = _SHA_FIELD


class StackManifest(BaseModel):
    """Versioned immutable contract for one explicit PR stack."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^rvw-stack-[A-Za-z0-9._-]+$")
    repo: str = Field(min_length=1)
    members: list[StackMember] = Field(min_length=2)

    @model_validator(mode="after")
    def _manifest_is_consistent(self) -> StackManifest:
        validated = validate_stack(self.members)
        if validated[0].repo != self.repo:
            raise ValueError("manifest repository does not match its members")
        return self


class MemberRunRef(BaseModel):
    """Reference and local verdict summary for one ordinary member run."""

    model_config = ConfigDict(extra="forbid")

    pr_number: int = Field(ge=1)
    run_id: str = Field(min_length=1)
    report_path: str = Field(min_length=1)
    verdict_counts: dict[str, int]

    @field_validator("verdict_counts")
    @classmethod
    def _counts_are_complete(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != _VERDICT_KEYS:
            raise ValueError("verdict_counts must contain CONFIRMED, REJECTED, and UNCERTAIN")
        if any(count < 0 for count in value.values()):
            raise ValueError("verdict counts must not be negative")
        return value


class Presence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNCERTAIN = "UNCERTAIN"


class LineageState(StrEnum):
    STILL_PRESENT = "STILL_PRESENT"
    FIXED_IN = "FIXED_IN"
    REGRESSED_IN = "REGRESSED_IN"
    UNCERTAIN = "UNCERTAIN"


class PresenceObservation(BaseModel):
    """One majority-voted claim observation at a concrete PR head."""

    model_config = ConfigDict(extra="forbid")

    pr_number: int = Field(ge=1)
    presence: Presence
    reason: str
    evidence: str
    replica_votes: list[Presence]


class FindingLineage(BaseModel):
    """An origin finding plus ordered observations at descendant heads."""

    model_config = ConfigDict(extra="forbid")

    lineage_id: str = Field(min_length=1)
    origin_pr: int = Field(ge=1)
    origin_run_id: str = Field(min_length=1)
    origin_finding_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    file: str = Field(min_length=1)
    line: int | None
    severity: Severity
    bodies: list[str] = Field(min_length=1)
    origin_verdict: Verdict
    observations: list[PresenceObservation] = Field(min_length=1)
    state: LineageState
    state_pr: int | None = None

    @model_validator(mode="after")
    def _history_is_ordered(self) -> FindingLineage:
        if self.origin_verdict is Verdict.REJECTED:
            raise ValueError("rejected findings cannot originate stack lineages")
        numbers = [item.pr_number for item in self.observations]
        if numbers[0] != self.origin_pr:
            raise ValueError("first lineage observation must be the origin PR")
        if any(current <= previous for previous, current in pairwise(numbers)):
            raise ValueError("lineage observations must use strictly increasing PR order")
        expected_state, expected_pr = derive_lineage_state(self.observations)
        if self.state is not expected_state or self.state_pr != expected_pr:
            raise ValueError("lineage state does not match its observations")
        return self


class _RepoView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nameWithOwner: str


class _PullRepo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    full_name: str


class _PullRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: str
    sha: str
    repo: _PullRepo | None


class _PullView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int
    html_url: str
    title: str
    body: str | None
    state: str
    merged: bool
    base: _PullRef
    head: _PullRef


def _run(command: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or str(exc)
        raise StackResolutionError(command, detail) from exc
    except OSError as exc:
        raise StackResolutionError(command, str(exc)) from exc
    return completed.stdout


def parse_pr_numbers(raw: str) -> list[int]:
    """Parse an explicit ordered comma-separated PR list."""

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 2 or any(not part for part in parts):
        raise ValueError("stack requires at least two pull-request numbers")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("stack pull-request values must be integers") from exc
    if any(number < 1 for number in numbers):
        raise ValueError("stack pull-request numbers must be positive")
    if len(numbers) != len(set(numbers)):
        raise ValueError("stack pull-request numbers must be unique")
    return numbers


def validate_stack(members: Sequence[StackMember]) -> list[StackMember]:
    """Require one ordered, direct, same-repository, open PR chain."""

    ordered = list(members)
    if len(ordered) < 2:
        raise StackInvariantError("stack must contain at least two pull requests")
    numbers = [member.number for member in ordered]
    if len(numbers) != len(set(numbers)):
        raise StackInvariantError("stack pull-request numbers must be unique")
    repos = {member.repo for member in ordered}
    if len(repos) != 1:
        raise StackInvariantError("all stack members must belong to the same repository")
    for member in ordered:
        if member.state != "open" or member.merged:
            raise StackInvariantError(
                f"pull request #{member.number} must remain open and unmerged"
            )
    for parent, child in pairwise(ordered):
        if child.base_ref != parent.head_ref or child.base_sha != parent.head_sha:
            raise StackInvariantError(
                f"stack edge #{parent.number} -> #{child.number} is not direct: "
                f"expected base {parent.head_ref}@{parent.head_sha}, "
                f"found {child.base_ref}@{child.base_sha}"
            )
    return ordered


def resolve_stack(
    numbers: Sequence[int],
    *,
    cwd: Path,
    repo: str | None = None,
    run: CommandRunner = _run,
) -> list[StackMember]:
    """Resolve explicit PR numbers through GitHub's REST representation."""

    requested = list(numbers)
    if len(requested) < 2:
        raise ValueError("stack requires at least two pull-request numbers")
    if len(requested) != len(set(requested)):
        raise ValueError("stack pull-request numbers must be unique")
    if any(number < 1 for number in requested):
        raise ValueError("stack pull-request numbers must be positive")

    repo_name = repo
    if repo_name is None:
        raw_repo = run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd)
        repo_name = _RepoView.model_validate_json(raw_repo).nameWithOwner

    members: list[StackMember] = []
    for number in requested:
        raw = run(["gh", "api", f"repos/{repo_name}/pulls/{number}"], cwd)
        pull = _PullView.model_validate_json(raw)
        if pull.number != number:
            raise StackInvariantError(
                f"GitHub returned pull request #{pull.number} while resolving #{number}"
            )
        if pull.base.repo is None:
            raise StackInvariantError(f"pull request #{number} has no base repository")
        members.append(
            StackMember(
                repo=pull.base.repo.full_name,
                number=pull.number,
                url=pull.html_url,
                title=pull.title,
                body=pull.body,
                state=pull.state,
                merged=pull.merged,
                base_ref=pull.base.ref,
                base_sha=pull.base.sha,
                head_ref=pull.head.ref,
                head_sha=pull.head.sha,
            )
        )
    return validate_stack(members)


def verify_manifest(
    manifest: StackManifest,
    current_members: Sequence[StackMember],
) -> None:
    """Fail when any persisted member identity, anchor, or edge has moved."""

    current = validate_stack(current_members)
    expected_numbers = [member.number for member in manifest.members]
    current_numbers = [member.number for member in current]
    if current_numbers != expected_numbers:
        raise StackInvariantError(
            f"stack member order changed: expected {expected_numbers}, found {current_numbers}"
        )
    compared_fields = (
        "repo",
        "state",
        "merged",
        "base_ref",
        "base_sha",
        "head_ref",
        "head_sha",
    )
    for expected, actual in zip(manifest.members, current, strict=True):
        changed = [
            field for field in compared_fields if getattr(expected, field) != getattr(actual, field)
        ]
        if changed:
            raise StackInvariantError(
                f"pull request #{expected.number} moved since planning: {', '.join(changed)}"
            )


def resolved_target_for_member(
    member: StackMember,
    *,
    cwd: Path,
    run: CommandRunner = _run,
) -> ResolvedTarget:
    """Build an ordinary target from the captured anchors and pinned checkout."""

    diff_args = [
        "git",
        "diff",
        "--binary",
        "--find-renames",
        member.base_sha,
        member.head_sha,
    ]
    names_args = [
        "git",
        "diff",
        "--name-only",
        member.base_sha,
        member.head_sha,
    ]
    diff = run(diff_args, cwd)
    names = run(names_args, cwd)
    return ResolvedTarget(
        kind="pr",
        repo=member.repo,
        base_sha=member.base_sha,
        head_sha=member.head_sha,
        changed_paths=[line for line in names.splitlines() if line],
        diff=diff,
        pr_number=member.number,
        pr_title=member.title,
        pr_body=member.body,
    )


def derive_lineage_state(
    observations: Sequence[PresenceObservation],
) -> tuple[LineageState, int | None]:
    """Derive the current lifecycle state from ordered head observations."""

    history = list(observations)
    if not history or history[0].presence is Presence.UNCERTAIN:
        return LineageState.UNCERTAIN, None
    if history[-1].presence is Presence.UNCERTAIN:
        return LineageState.UNCERTAIN, None

    previous = history[0].presence
    last_fixed_pr: int | None = None
    last_regressed_pr: int | None = None
    for item in history[1:]:
        if item.presence is Presence.UNCERTAIN:
            continue
        if previous is Presence.PRESENT and item.presence is Presence.ABSENT:
            last_fixed_pr = item.pr_number
        elif previous is Presence.ABSENT and item.presence is Presence.PRESENT:
            last_regressed_pr = item.pr_number
        previous = item.presence

    if history[-1].presence is Presence.ABSENT:
        if last_fixed_pr is None:
            return LineageState.UNCERTAIN, None
        return LineageState.FIXED_IN, last_fixed_pr
    if last_regressed_pr is not None:
        return LineageState.REGRESSED_IN, last_regressed_pr
    return LineageState.STILL_PRESENT, None


def _lineage_id(origin_pr: int, origin_run_id: str, origin_finding_id: str) -> str:
    identity = f"{origin_pr}:{origin_run_id}:{origin_finding_id}".encode()
    return hashlib.sha1(identity).hexdigest()


def make_origin_lineage(
    *,
    origin_pr: int,
    origin_run_id: str,
    origin_finding_id: str,
    rule_id: str,
    file: str,
    line: int | None,
    severity: Severity,
    bodies: Sequence[str],
    origin_verdict: Verdict,
    origin_reason: str,
    origin_evidence: str,
) -> FindingLineage:
    """Create a lineage without manufacturing cross-PR finding identity."""

    if origin_verdict not in {Verdict.CONFIRMED, Verdict.UNCERTAIN}:
        raise ValueError("only confirmed or uncertain findings are actionable stack origins")
    presence = Presence.PRESENT if origin_verdict is Verdict.CONFIRMED else Presence.UNCERTAIN
    first = PresenceObservation(
        pr_number=origin_pr,
        presence=presence,
        reason=origin_reason,
        evidence=origin_evidence,
        replica_votes=[presence],
    )
    state, state_pr = derive_lineage_state([first])
    return FindingLineage(
        lineage_id=_lineage_id(origin_pr, origin_run_id, origin_finding_id),
        origin_pr=origin_pr,
        origin_run_id=origin_run_id,
        origin_finding_id=origin_finding_id,
        rule_id=rule_id,
        file=file,
        line=line,
        severity=severity,
        bodies=list(bodies),
        origin_verdict=origin_verdict,
        observations=[first],
        state=state,
        state_pr=state_pr,
    )


def append_observation(
    lineage: FindingLineage,
    observation: PresenceObservation,
) -> FindingLineage:
    """Return a lineage with one later observation and refreshed state."""

    if observation.pr_number <= lineage.observations[-1].pr_number:
        raise ValueError("lineage observations must advance to a later PR")
    observations = [*lineage.observations, observation]
    state, state_pr = derive_lineage_state(observations)
    return lineage.model_copy(
        update={
            "observations": observations,
            "state": state,
            "state_pr": state_pr,
        }
    )


def origin_lineages(
    *,
    pr_number: int,
    run_id: str,
    merged: MergeResult,
    outcome: AdjudicationOutcome,
) -> list[FindingLineage]:
    """Convert current-run actionable groups into independent origin claims."""

    lineages: list[FindingLineage] = []
    for group in merged.groups:
        verdict = outcome.verdicts.get(group.key)
        if verdict not in {Verdict.CONFIRMED, Verdict.UNCERTAIN}:
            continue
        lineages.append(
            make_origin_lineage(
                origin_pr=pr_number,
                origin_run_id=run_id,
                origin_finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                line=group.line,
                severity=group.severity,
                bodies=group.bodies,
                origin_verdict=verdict,
                origin_reason=outcome.reasons.get(group.key, ""),
                origin_evidence=outcome.evidence.get(group.key, ""),
            )
        )
    return lineages


__all__ = [
    "CommandRunner",
    "FindingLineage",
    "LineageState",
    "MemberRunRef",
    "Presence",
    "PresenceObservation",
    "StackInvariantError",
    "StackManifest",
    "StackMember",
    "StackResolutionError",
    "append_observation",
    "derive_lineage_state",
    "make_origin_lineage",
    "origin_lineages",
    "parse_pr_numbers",
    "resolve_stack",
    "resolved_target_for_member",
    "validate_stack",
    "verify_manifest",
]
