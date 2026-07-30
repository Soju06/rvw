from __future__ import annotations

from rvw.schema import Severity, Verdict
from rvw.stack import (
    MemberRunRef,
    Presence,
    PresenceObservation,
    StackManifest,
    StackMember,
    append_observation,
    make_origin_lineage,
)
from rvw.stack_report import render_stack_report


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


def test_report_separates_pr_local_findings_from_stack_tip_state() -> None:
    manifest = StackManifest(
        run_id="rvw-stack-20260730-120000-000001-prs-1-3",
        repo="owner/repo",
        members=valid_members(),
    )
    runs = [
        MemberRunRef(
            pr_number=number,
            run_id=f"rvw-member-{number}",
            report_path=f"/tmp/rvw/rvw-member-{number}/report.md",
            verdict_counts={
                "CONFIRMED": 1 if number == 1 else 0,
                "REJECTED": 0,
                "UNCERTAIN": 0,
            },
        )
        for number in (1, 2, 3)
    ]
    lineage = make_origin_lineage(
        origin_pr=1,
        origin_run_id="rvw-member-1",
        origin_finding_id="finding-1",
        rule_id="bug/correctness",
        file="src/a.py",
        line=4,
        severity=Severity.WARNING,
        bodies=["Cache remains stale."],
        origin_verdict=Verdict.CONFIRMED,
        origin_reason="confirmed",
        origin_evidence="return stale",
    )
    lineage = append_observation(
        lineage,
        PresenceObservation(
            pr_number=2,
            presence=Presence.PRESENT,
            reason="still there",
            evidence="return stale",
            replica_votes=[Presence.PRESENT],
        ),
    )
    lineage = append_observation(
        lineage,
        PresenceObservation(
            pr_number=3,
            presence=Presence.ABSENT,
            reason="fixed",
            evidence="return fresh",
            replica_votes=[Presence.ABSENT],
        ),
    )

    report = render_stack_report(manifest, runs, [lineage])

    assert "PR #1 로컬 결과" in report
    assert "CONFIRMED | 1" in report
    assert "FIXED_IN #3" in report
    assert "PR #1 → PR #2 → PR #3" in report
    assert "PRESENT → PRESENT → ABSENT" in report
    assert "Cache remains stale." in report
