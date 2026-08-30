from __future__ import annotations

import json
from pathlib import Path

import pytest

import rvw.target as target_module
from rvw.target import TargetResolutionError, resolve_target

Command = tuple[str, ...]


def install_fake_run(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[Command, str | Exception],
) -> list[Command]:
    calls: list[Command] = []

    def fake_run(cmd: list[str], cwd: Path) -> str:
        del cwd
        key = tuple(cmd)
        calls.append(key)
        response = responses[key]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(target_module, "_run", fake_run)
    return calls


REPO_RESPONSE = json.dumps({"nameWithOwner": "octo/widgets"})


def test_resolve_uncommitted_includes_worktree_shape_and_untracked_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "new.txt").write_text("new line\n", encoding="utf-8")
    responses: dict[Command, str | Exception] = {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-parse", "HEAD"): "abc123def456\n",
        ("git", "status", "--porcelain"): " M src/changed.py\n?? new.txt\n",
        ("git", "ls-files", "--others", "--exclude-standard", "-z"): "new.txt\0",
        ("git", "diff", "HEAD"): "diff --git a/src/changed.py b/src/changed.py\n",
    }
    install_fake_run(monkeypatch, responses)

    resolved = resolve_target("--uncommitted", cwd=tmp_path)

    assert resolved.kind == "uncommitted"
    assert resolved.repo == "octo/widgets"
    assert resolved.base_sha is None
    assert resolved.head_sha == "abc123def456"
    assert resolved.changed_paths == ["src/changed.py", "new.txt"]
    assert resolved.diff.startswith("diff --git a/src/changed.py b/src/changed.py\n")
    assert "--- /dev/null\n+++ b/new.txt\n" in resolved.diff
    assert "+new line\n" in resolved.diff
    assert resolved.pr_number is None


def test_resolve_uncommitted_expands_untracked_directory_without_following_symlinks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "openspec" / "changes" / "archive" / "example"
    nested = archive / "specs" / "discovery"
    nested.mkdir(parents=True)
    (archive / "proposal.md").write_text("proposal\n", encoding="utf-8")
    (nested / "spec.md").write_text("spec\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("must not be read\n", encoding="utf-8")
    (archive / "outside-link.md").symlink_to(outside)
    responses: dict[Command, str | Exception] = {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-parse", "HEAD"): "abc123def456\n",
        ("git", "status", "--porcelain"): "?? openspec/changes/archive/example/\n",
        ("git", "ls-files", "--others", "--exclude-standard", "-z"): (
            "openspec/changes/archive/example/proposal.md\0"
            "openspec/changes/archive/example/specs/discovery/spec.md\0"
            "openspec/changes/archive/example/outside-link.md\0"
        ),
        ("git", "diff", "HEAD"): "",
    }
    install_fake_run(monkeypatch, responses)

    resolved = resolve_target("uncommitted", cwd=tmp_path)

    assert resolved.changed_paths == [
        "openspec/changes/archive/example/proposal.md",
        "openspec/changes/archive/example/specs/discovery/spec.md",
    ]
    assert "+++ b/openspec/changes/archive/example/proposal.md" in resolved.diff
    assert "+++ b/openspec/changes/archive/example/specs/discovery/spec.md" in resolved.diff
    assert "outside-link.md" not in resolved.diff
    assert "must not be read" not in resolved.diff


def test_resolve_uncommitted_excludes_ignored_files_from_untracked_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "openspec" / "changes" / "archive" / "example"
    archive.mkdir(parents=True)
    included = archive / "proposal.md"
    ignored = archive / ".env"
    included.write_text("proposal\n", encoding="utf-8")
    ignored.write_text("TOP_SECRET=must-not-reach-a-prompt\n", encoding="utf-8")
    responses: dict[Command, str | Exception] = {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-parse", "HEAD"): "abc123def456\n",
        ("git", "status", "--porcelain"): "?? openspec/changes/archive/example/\n",
        ("git", "ls-files", "--others", "--exclude-standard", "-z"): (
            "openspec/changes/archive/example/proposal.md\0"
        ),
        ("git", "diff", "HEAD"): "",
    }
    install_fake_run(monkeypatch, responses)

    resolved = resolve_target("uncommitted", cwd=tmp_path)

    assert resolved.changed_paths == ["openspec/changes/archive/example/proposal.md"]
    assert "proposal.md" in resolved.diff
    assert ".env" not in resolved.diff
    assert "TOP_SECRET" not in resolved.diff


def test_resolve_uncommitted_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    responses: dict[Command, str | Exception] = {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-parse", "HEAD"): "abc123\n",
        ("git", "status", "--porcelain"): "",
        ("git", "ls-files", "--others", "--exclude-standard", "-z"): "",
        ("git", "diff", "HEAD"): "",
    }
    install_fake_run(monkeypatch, responses)

    assert resolve_target("uncommitted", cwd=tmp_path).kind == "uncommitted"


def test_resolve_commit_uses_parent_as_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = "abcdef1"
    responses: dict[Command, str | Exception] = {
        ("git", "cat-file", "-e", f"{spec}^{{commit}}"): "",
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-list", "--parents", "-n", "1", spec): "abcdef123 parent456\n",
        ("git", "show", spec, "--format="): "commit diff\n",
        ("git", "show", spec, "--format=", "--name-only"): "src/a.py\nsrc/b.py\n",
    }
    install_fake_run(monkeypatch, responses)

    resolved = resolve_target(spec, cwd=tmp_path)

    assert resolved.kind == "commit"
    assert resolved.repo == "octo/widgets"
    assert resolved.base_sha == "parent456"
    assert resolved.head_sha == "abcdef123"
    assert resolved.changed_paths == ["src/a.py", "src/b.py"]
    assert resolved.diff == "commit diff\n"


def pr_responses(number: int) -> dict[Command, str | Exception]:
    metadata = {
        "number": number,
        "title": "Fix widget race",
        "body": "Synchronizes widget updates.",
        "headRefOid": "head123",
        "headRefName": "fix/widget-race",
    }
    return {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        (
            "gh",
            "pr",
            "view",
            str(number),
            "--json",
            "number,title,body,headRefOid,headRefName",
        ): json.dumps(metadata),
        # gh pr view --json does NOT expose baseRefOid (live-verified 2026-07-27);
        # the recorded base SHA comes from the REST pulls endpoint instead.
        ("gh", "api", f"repos/octo/widgets/pulls/{number}", "--jq", ".base.sha"): "base123\n",
        ("gh", "api", f"repos/acme/rockets/pulls/{number}", "--jq", ".base.sha"): "base123\n",
        ("gh", "pr", "diff", str(number)): "pr diff\n",
        ("gh", "pr", "diff", str(number), "--name-only"): "src/widget.py\n",
    }


def test_resolve_pr_number_populates_pr_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_run(monkeypatch, pr_responses(42))

    resolved = resolve_target("42", cwd=tmp_path)

    assert resolved.kind == "pr"
    assert resolved.repo == "octo/widgets"
    assert resolved.base_sha == "base123"
    assert resolved.head_sha == "head123"
    assert resolved.changed_paths == ["src/widget.py"]
    assert resolved.diff == "pr diff\n"
    assert resolved.pr_number == 42
    assert resolved.pr_title == "Fix widget race"
    assert resolved.pr_body == "Synchronizes widget updates."


def test_resolve_pr_url_uses_repo_from_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    responses = pr_responses(17)
    del responses[("gh", "repo", "view", "--json", "nameWithOwner")]
    calls = install_fake_run(monkeypatch, responses)

    resolved = resolve_target("https://github.com/acme/rockets/pull/17", cwd=tmp_path)

    assert resolved.kind == "pr"
    assert resolved.repo == "acme/rockets"
    assert resolved.pr_number == 17
    assert ("gh", "repo", "view", "--json", "nameWithOwner") not in calls


def test_all_digit_spec_routes_to_pr_before_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = install_fake_run(monkeypatch, pr_responses(1234567))

    assert resolve_target("1234567", cwd=tmp_path).kind == "pr"
    assert not any(call[:2] == ("git", "cat-file") for call in calls)


def test_subprocess_failure_reports_failed_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command = ("gh", "repo", "view", "--json", "nameWithOwner")
    failure = TargetResolutionError(list(command), "gh failed")
    install_fake_run(monkeypatch, {command: failure})

    with pytest.raises(TargetResolutionError, match="gh repo view --json nameWithOwner"):
        resolve_target("uncommitted", cwd=tmp_path)
