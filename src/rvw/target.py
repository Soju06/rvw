"""Resolve review target specifications into immutable review inputs."""

from __future__ import annotations

import ast
import difflib
import re
import shlex
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_COMMIT_SPEC = re.compile(r"[0-9a-fA-F]{7,40}")
_PR_URL = re.compile(
    r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<name>[^/\s]+)/pull/(?P<number>\d+)"
    r"(?:[/?#]|$)"
)
_PR_FIELDS = "number,title,body,headRefOid,headRefName"


class ResolvedTarget(BaseModel):
    """Repository and diff data needed by downstream review stages."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pr", "commit", "uncommitted"]
    repo: str
    base_sha: str | None
    head_sha: str
    changed_paths: list[str]
    diff: str
    pr_number: int | None = None
    pr_title: str | None = None
    pr_body: str | None = None


class TargetResolutionError(RuntimeError):
    """A subprocess needed to resolve a target failed."""

    def __init__(self, command: list[str], detail: str | None = None) -> None:
        self.command = command
        message = f"target resolution command failed: {shlex.join(command)}"
        if detail:
            message = f"{message}: {detail.strip()}"
        super().__init__(message)


class _RepoView(BaseModel):
    nameWithOwner: str


class _PrView(BaseModel):
    number: int
    title: str
    body: str | None
    headRefOid: str
    headRefName: str


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or str(exc)
        raise TargetResolutionError(cmd, detail) from exc
    except OSError as exc:
        raise TargetResolutionError(cmd, str(exc)) from exc
    return completed.stdout


def _repo_name(cwd: Path) -> str:
    raw = _run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd)
    return _RepoView.model_validate_json(raw).nameWithOwner


def _decode_status_path(raw_path: str) -> str:
    path = raw_path.rsplit(" -> ", maxsplit=1)[-1]
    if path.startswith('"') and path.endswith('"'):
        decoded = ast.literal_eval(path)
        if isinstance(decoded, str):
            return decoded
    return path


def _status_paths(status: str) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    untracked: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = _decode_status_path(line[3:])
        changed.append(path)
        if line[:2] == "??":
            untracked.append(path)
    return changed, untracked


def _untracked_diff(path: str, cwd: Path) -> str:
    disk_path = cwd / path
    try:
        contents = disk_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return (
            f"diff --git a/{path} b/{path}\n"
            f"new file mode 100644\n"
            f"Binary files /dev/null and b/{path} differ\n"
        )

    lines = contents.splitlines(keepends=True)
    body = "".join(
        difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{path}", lineterm="\n")
    )
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n{body}"


def _combine_diffs(parts: list[str]) -> str:
    return "".join(part if not part or part.endswith("\n") else f"{part}\n" for part in parts)


def _resolve_uncommitted(cwd: Path) -> ResolvedTarget:
    repo = _repo_name(cwd)
    head_sha = _run(["git", "rev-parse", "HEAD"], cwd).strip()
    status = _run(["git", "status", "--porcelain"], cwd)
    changed_paths, untracked_paths = _status_paths(status)
    tracked_diff = _run(["git", "diff", "HEAD"], cwd)
    diff = _combine_diffs([tracked_diff, *(_untracked_diff(path, cwd) for path in untracked_paths)])
    return ResolvedTarget(
        kind="uncommitted",
        repo=repo,
        base_sha=None,
        head_sha=head_sha,
        changed_paths=changed_paths,
        diff=diff,
    )


def _resolve_commit(spec: str, cwd: Path) -> ResolvedTarget:
    _run(["git", "cat-file", "-e", f"{spec}^{{commit}}"], cwd)
    repo = _repo_name(cwd)
    ancestry = _run(["git", "rev-list", "--parents", "-n", "1", spec], cwd).split()
    if not ancestry:
        raise TargetResolutionError(
            ["git", "rev-list", "--parents", "-n", "1", spec], "empty output"
        )
    head_sha = ancestry[0]
    base_sha = ancestry[1] if len(ancestry) > 1 else None
    diff = _run(["git", "show", spec, "--format="], cwd)
    names = _run(["git", "show", spec, "--format=", "--name-only"], cwd)
    return ResolvedTarget(
        kind="commit",
        repo=repo,
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=[line for line in names.splitlines() if line],
        diff=diff,
    )


def _pr_base_sha(number: int, repo: str, cwd: Path) -> str:
    """Fetch the recorded base SHA via REST.

    `gh pr view --json` does not expose `baseRefOid` (verified live 2026-07-27);
    the REST pulls endpoint is the documented source for the recorded base SHA.
    """

    raw = _run(["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".base.sha"], cwd)
    return raw.strip()


def _resolve_pr(number: int, cwd: Path, repo_from_url: str | None = None) -> ResolvedTarget:
    repo = repo_from_url or _repo_name(cwd)
    raw = _run(["gh", "pr", "view", str(number), "--repo", repo, "--json", _PR_FIELDS], cwd)
    metadata = _PrView.model_validate_json(raw)
    diff = _run(["gh", "pr", "diff", str(number), "--repo", repo], cwd)
    names = _run(["gh", "pr", "diff", str(number), "--repo", repo, "--name-only"], cwd)
    return ResolvedTarget(
        kind="pr",
        repo=repo,
        base_sha=_pr_base_sha(number, repo, cwd),
        head_sha=metadata.headRefOid,
        changed_paths=[line for line in names.splitlines() if line],
        diff=diff,
        pr_number=metadata.number,
        pr_title=metadata.title,
        pr_body=metadata.body,
    )


def resolve_target(spec: str, *, cwd: Path) -> ResolvedTarget:
    """Resolve a PR, commit, or uncommitted-worktree target.

    All-digit specifications are always interpreted as PR numbers, even when the
    same text could name a hexadecimal commit. PR mode wins this ambiguity.
    """

    if spec in {"--uncommitted", "uncommitted"}:
        return _resolve_uncommitted(cwd)

    url_match = _PR_URL.fullmatch(spec)
    if url_match:
        repo = f"{url_match.group('owner')}/{url_match.group('name')}"
        return _resolve_pr(int(url_match.group("number")), cwd, repo)

    if spec.isdigit():
        return _resolve_pr(int(spec), cwd)

    if _COMMIT_SPEC.fullmatch(spec):
        return _resolve_commit(spec, cwd)

    raise ValueError(f"unsupported target specification: {spec!r}")
