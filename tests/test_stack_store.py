from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rvw.schema import Severity, Verdict
from rvw.stack import MemberRunRef, StackManifest, StackMember, make_origin_lineage
from rvw.stack_store import StackRunNotFound, StackStageMissing, StackStore


def valid_members() -> list[StackMember]:
    first = StackMember(
        repo="owner/repo",
        number=1,
        url="https://github.com/owner/repo/pull/1",
        title="PR 1",
        state="open",
        merged=False,
        base_ref="main",
        base_sha="0" * 40,
        head_ref="stack-1",
        head_sha="1" * 40,
    )
    second = first.model_copy(
        update={
            "number": 2,
            "url": "https://github.com/owner/repo/pull/2",
            "title": "PR 2",
            "base_ref": first.head_ref,
            "base_sha": first.head_sha,
            "head_ref": "stack-2",
            "head_sha": "2" * 40,
        }
    )
    third = second.model_copy(
        update={
            "number": 3,
            "url": "https://github.com/owner/repo/pull/3",
            "title": "PR 3",
            "base_ref": second.head_ref,
            "base_sha": second.head_sha,
            "head_ref": "stack-3",
            "head_sha": "3" * 40,
        }
    )
    return [first, second, third]


def manifest(run_id: str) -> StackManifest:
    return StackManifest(run_id=run_id, repo="owner/repo", members=valid_members())


def member_run(number: int) -> MemberRunRef:
    return MemberRunRef(
        pr_number=number,
        run_id=f"rvw-member-{number}",
        report_path=f"/tmp/rvw/rvw-member-{number}/report.md",
        verdict_counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
    )


def test_stack_store_round_trips_strict_artifacts(tmp_path: Path) -> None:
    handle = StackStore(tmp_path).create([1, 2, 3])
    saved_manifest = manifest(handle.run_id)
    lineage = make_origin_lineage(
        origin_pr=1,
        origin_run_id="rvw-member-1",
        origin_finding_id="finding-1",
        rule_id="bug/correctness",
        file="src/a.py",
        line=4,
        severity=Severity.WARNING,
        bodies=["broken"],
        origin_verdict=Verdict.CONFIRMED,
        origin_reason="confirmed",
        origin_evidence="broken()",
    )

    handle.save_manifest(saved_manifest)
    handle.save_member_runs([member_run(1), member_run(2)])
    handle.save_lineages([lineage])
    handle.save_report("# stack report\n")

    reopened = StackStore(tmp_path).open(handle.run_id)
    assert reopened.load_manifest() == saved_manifest
    assert reopened.load_member_runs() == [member_run(1), member_run(2)]
    assert reopened.load_lineages() == [lineage]
    assert reopened.load_report() == "# stack report\n"


def test_partial_member_runs_remain_loadable(tmp_path: Path) -> None:
    handle = StackStore(tmp_path).create([1, 2, 3])
    handle.save_manifest(manifest(handle.run_id))
    handle.save_member_runs([member_run(1)])

    assert [item.pr_number for item in handle.load_member_runs()] == [1]
    with pytest.raises(StackStageMissing, match="complete"):
        handle.require_complete()


def test_stack_store_rejects_path_traversal_run_id(tmp_path: Path) -> None:
    with pytest.raises(StackRunNotFound):
        StackStore(tmp_path).open("../escape")


def test_stack_store_rejects_extra_json_fields(tmp_path: Path) -> None:
    handle = StackStore(tmp_path).create([1, 2])
    saved = manifest(handle.run_id)
    payload = saved.model_dump(mode="json")
    payload["unexpected"] = True
    (handle.dir / "stack-manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        handle.load_manifest()
