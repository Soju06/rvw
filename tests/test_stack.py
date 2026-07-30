from __future__ import annotations

import json
from pathlib import Path

import pytest

from rvw.stack import (
    StackInvariantError,
    StackManifest,
    StackMember,
    parse_pr_numbers,
    resolve_stack,
    resolved_target_for_member,
    validate_stack,
    verify_manifest,
)


def member(
    number: int,
    *,
    repo: str = "owner/repo",
    base_ref: str | None = None,
    base_sha: str | None = None,
    head_ref: str | None = None,
    head_sha: str | None = None,
    state: str = "open",
    merged: bool = False,
) -> StackMember:
    return StackMember(
        repo=repo,
        number=number,
        url=f"https://github.com/{repo}/pull/{number}",
        title=f"PR {number}",
        body=f"Body {number}",
        state=state,
        merged=merged,
        base_ref=base_ref or ("main" if number == 1 else f"stack-{number - 1}"),
        base_sha=base_sha or (str(number - 1) * 40)[:40],
        head_ref=head_ref or f"stack-{number}",
        head_sha=head_sha or (str(number) * 40)[:40],
    )


def valid_members() -> list[StackMember]:
    first = member(1, base_sha="0" * 40, head_sha="1" * 40)
    second = member(
        2,
        base_ref=first.head_ref,
        base_sha=first.head_sha,
        head_sha="2" * 40,
    )
    third = member(
        3,
        base_ref=second.head_ref,
        base_sha=second.head_sha,
        head_sha="3" * 40,
    )
    return [first, second, third]


def manifest_fixture() -> StackManifest:
    return StackManifest(
        run_id="rvw-stack-20260730-120000-000001-prs-1-3",
        repo="owner/repo",
        members=valid_members(),
    )


def test_parse_pr_numbers_preserves_order_and_whitespace() -> None:
    assert parse_pr_numbers("11, 12,14") == [11, 12, 14]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "at least two"),
        ("11", "at least two"),
        ("11,12,11", "unique"),
        ("11,0", "positive"),
        ("11,nope", "integer"),
    ],
)
def test_parse_pr_numbers_rejects_invalid_lists(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_pr_numbers(raw)


def test_validate_stack_accepts_direct_same_repo_chain() -> None:
    assert validate_stack(valid_members()) == valid_members()


def test_validate_stack_rejects_cross_repo_member() -> None:
    members = valid_members()
    members[1] = members[1].model_copy(update={"repo": "other/repo"})

    with pytest.raises(StackInvariantError, match="same repository"):
        validate_stack(members)


def test_validate_stack_rejects_broken_ref_or_sha_edge() -> None:
    members = valid_members()
    members[2] = members[2].model_copy(update={"base_sha": "f" * 40})

    with pytest.raises(StackInvariantError, match=r"#2.*#3"):
        validate_stack(members)


def test_resolve_stack_uses_rest_metadata_in_caller_order(tmp_path: Path) -> None:
    expected = valid_members()
    calls: list[tuple[str, ...]] = []

    def fake_run(command: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        calls.append(tuple(command))
        if command[:3] == ["gh", "repo", "view"]:
            return json.dumps({"nameWithOwner": "owner/repo"})
        number = int(command[-1].rsplit("/", maxsplit=1)[-1])
        item = next(member for member in expected if member.number == number)
        return json.dumps(
            {
                "number": item.number,
                "html_url": item.url,
                "title": item.title,
                "body": item.body,
                "state": item.state,
                "merged": item.merged,
                "base": {
                    "ref": item.base_ref,
                    "sha": item.base_sha,
                    "repo": {"full_name": item.repo},
                },
                "head": {
                    "ref": item.head_ref,
                    "sha": item.head_sha,
                    "repo": {"full_name": item.repo},
                },
            }
        )

    resolved = resolve_stack([1, 2, 3], cwd=tmp_path, run=fake_run)

    assert resolved == expected
    assert [call[-1] for call in calls[1:]] == [
        "repos/owner/repo/pulls/1",
        "repos/owner/repo/pulls/2",
        "repos/owner/repo/pulls/3",
    ]


@pytest.mark.parametrize(
    "changed",
    [
        {"state": "closed"},
        {"merged": True},
        {"base_ref": "other-base"},
        {"base_sha": "a" * 40},
        {"head_ref": "other-head"},
        {"head_sha": "b" * 40},
    ],
)
def test_verify_manifest_rejects_moved_or_closed_member(changed: dict[str, object]) -> None:
    manifest = manifest_fixture()
    current = list(manifest.members)
    current[1] = current[1].model_copy(update=changed)

    with pytest.raises(StackInvariantError, match=r"#2"):
        verify_manifest(manifest, current)


def test_resolved_target_for_member_uses_captured_anchors(
    tmp_path: Path,
) -> None:
    captured = valid_members()[1]
    calls: list[tuple[str, ...]] = []

    def fake_run(command: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        calls.append(tuple(command))
        if "--name-only" in command:
            return "src/a.py\nsrc/b.py\n"
        return "diff --git a/src/a.py b/src/a.py\n"

    target = resolved_target_for_member(captured, cwd=tmp_path, run=fake_run)

    assert target.repo == captured.repo
    assert target.pr_number == captured.number
    assert target.base_sha == captured.base_sha
    assert target.head_sha == captured.head_sha
    assert target.changed_paths == ["src/a.py", "src/b.py"]
    assert target.diff.startswith("diff --git")
    assert all(captured.base_sha in call and captured.head_sha in call for call in calls)
