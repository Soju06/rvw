from __future__ import annotations

from test_publish import merged_fixture, outcome_fixture, target_fixture
from test_stack_report import valid_members

from rvw.gate import DispositionDecision, DispositionDocument, DispositionRecord, build_gate_verdict
from rvw.presentation import PresentationConfig
from rvw.schema import Severity, Verdict
from rvw.special_publication import render_gate_publication, render_stack_publication
from rvw.stack import StackManifest, make_origin_lineage


def test_gate_publication_retains_human_disposition_and_evidence_only() -> None:
    merged = merged_fixture()
    outcome = outcome_fixture(merged)
    outcome = outcome.model_copy(
        update={"evidence": dict.fromkeys(outcome.evidence, "return stale")}
    )
    verdict = build_gate_verdict(
        run_id="private-run-id",
        target=target_fixture(),
        coverage=[],
        merged=merged,
        outcome=outcome,
        dispositions=DispositionDocument(
            schema_version=1,
            dispositions=[
                DispositionRecord(
                    finding_id=group.key,
                    decision=DispositionDecision.ACCEPTED,
                    reason="The owner accepted this risk.",
                )
                for group in merged.groups
                if outcome.verdicts[group.key] is Verdict.CONFIRMED
            ],
        ),
        actor="private-owner",
        actor_permission="admin",
    )
    report = render_gate_publication(
        verdict, merged, outcome, PresentationConfig(footer="<footer>")
    )
    for text in (
        "PASS",
        "Accepted",
        "The owner accepted this risk.",
        "src/a.py:10",
        "`rule/inline`",
        "```\nreturn stale\n```",
        "&lt;footer&gt;",
    ):
        assert text in report
    for text in (
        "private-run-id",
        "private-owner",
        target_fixture().head_sha,
        "REJECTED-BODY",
        "Replica agreement",
        merged.groups[0].key,
    ):
        assert text not in report


def test_stack_publication_localizes_state_and_preserves_verbatim_evidence() -> None:
    manifest = StackManifest(run_id="rvw-stack-private", repo="owner/repo", members=valid_members())
    lineage = make_origin_lineage(
        origin_pr=1,
        origin_run_id="private-origin-run",
        origin_finding_id="private-finding-id",
        rule_id="rule/cache",
        file="src/cache.py",
        line=10,
        severity=Severity.WARNING,
        bodies=["오래된 캐시를 반환합니다."],
        origin_verdict=Verdict.CONFIRMED,
        origin_reason="캐시를 무효화해야 합니다.",
        origin_evidence="return `stale`",
    )
    report = render_stack_publication(manifest, [], [lineage], PresentationConfig(locale="ko"))
    for text in (
        "경고",
        "문제가 남아 있습니다",
        "src/cache.py:10",
        "`rule/cache`",
        "캐시를 무효화해야 합니다.",
        "```\nreturn `stale`\n```",
    ):
        assert text in report
    for text in (
        manifest.run_id,
        "private-origin-run",
        "private-finding-id",
        manifest.members[0].head_sha,
        "Votes",
        "STILL_PRESENT",
    ):
        assert text not in report
