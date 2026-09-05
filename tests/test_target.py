from __future__ import annotations

import json
import os
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


def test_resolve_uncommitted_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    responses: dict[Command, str | Exception] = {
        ("gh", "repo", "view", "--json", "nameWithOwner"): REPO_RESPONSE,
        ("git", "rev-parse", "HEAD"): "abc123\n",
        ("git", "status", "--porcelain"): "",
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


def pr_responses(number: int, repo: str = "octo/widgets") -> dict[Command, str | Exception]:
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
            "--repo",
            repo,
            "--json",
            "number,title,body,headRefOid,headRefName",
        ): json.dumps(metadata),
        # gh pr view --json does NOT expose baseRefOid (live-verified 2026-07-27);
        # the recorded base SHA comes from the REST pulls endpoint instead.
        ("gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".base.sha"): "base123\n",
        ("gh", "pr", "diff", str(number), "--repo", repo): "pr diff\n",
        ("gh", "pr", "diff", str(number), "--repo", repo, "--name-only"): "src/widget.py\n",
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
    responses = pr_responses(17, "acme/rockets")
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


def test_pr_url_binds_every_query_despite_unrelated_repository_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GH_REPO", "unrelated/checkout")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "number": 17,
                    "title": "Fixture",
                    "body": "",
                    "headRefOid": "head123",
                    "headRefName": "fixture",
                }
            )
        if cmd[:3] == ["gh", "pr", "diff"]:
            return "fixture.py\n" if "--name-only" in cmd else "fixture diff\n"
        if cmd[:2] == ["gh", "api"]:
            return "base123\n"
        pytest.fail(f"unexpected target query: {cmd}")

    monkeypatch.setattr(target_module, "_run", fake_run)
    resolved = resolve_target("https://github.com/acme/rockets/pull/17", cwd=tmp_path)

    assert resolved.repo == "acme/rockets"
    assert len(calls) == 4
    for cmd in calls:
        if cmd[:2] == ["gh", "api"]:
            assert cmd[2] == "repos/acme/rockets/pulls/17"
        else:
            assert "--repo" in cmd, f"PR query is not bound to its repository: {cmd}"
            assert cmd[cmd.index("--repo") + 1] == "acme/rockets"
    assert os.environ["GH_REPO"] == "unrelated/checkout"
