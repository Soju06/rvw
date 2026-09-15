import json

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding
from rvw.merge import merge
from rvw.policy import PublishPolicy
from rvw.presentation import PresentationConfig
from rvw.publication import render_publication
from rvw.publish import _confirmed_inline_groups, publish_review
from rvw.report import render_report
from rvw.schema import EffectiveSeverity, FindingScope, Severity, Tier, Verdict
from rvw.store import RunStore
from rvw.synthesis import SynthesisDocument, SynthesisFinding, build_synthesis_prompt
from rvw.target import ResolvedTarget


def _review():
    findings = [
        EnrichedFinding(
            rule_id=f"rule/{scope.value}",
            file=file,
            hunk_id="h",
            line=line,
            severity=Severity.BLOCKER,
            body=f"body {scope.value}",
            anchorable=True,
            lane_id="lane",
            replica=1,
            scope=scope,
        )
        for scope, file, line in (
            (FindingScope.CHANGED, "src/new.py", 2),
            (FindingScope.UNCHANGED_IN_FILE, "src/new.py", 80),
            (FindingScope.OUTSIDE_DIFF, "src/old.py", 4),
        )
    ]
    findings.append(
        EnrichedFinding(
            rule_id="rule/warning",
            file="src/new.py",
            hunk_id="h",
            line=3,
            severity=Severity.WARNING,
            body="body warning",
            anchorable=True,
            lane_id="lane",
            replica=1,
            scope=FindingScope.CHANGED,
        )
    )
    merged = merge(findings, lane_tiers={"lane": Tier.BASE})
    outside = next(group for group in merged.groups if group.scope is FindingScope.OUTSIDE_DIFF)
    outcome = AdjudicationOutcome(
        verdicts={
            group.key: Verdict.UNCERTAIN if group.key == outside.key else Verdict.CONFIRMED
            for group in merged.groups
        },
        reasons={group.key: "confirmed" for group in merged.groups},
        evidence={group.key: "evidence" for group in merged.groups},
        replica_votes={
            group.key: [Verdict.UNCERTAIN if group.key == outside.key else Verdict.CONFIRMED]
            for group in merged.groups
        },
        unresolved=[outside.key],
        coerced_rejections=0,
    )
    return merged, outcome


def _target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/new.py"],
        diff="",
        pr_number=1,
    )


def test_report_and_publication_separate_demoted_findings() -> None:
    merged, outcome = _review()
    publication = render_publication(
        merged=merged, outcome=outcome, presentation=PresentationConfig(locale="ko")
    )
    report = render_report(
        target=_target(), merged=merged, outcome=outcome, coverage=[], budget=None, locale="ko"
    )
    for rendered in (publication, report):
        reference = rendered.split("## 참고 · 변경 범위 밖 (기존 코드)", 1)[1]
        assert "이 PR의 변경 범위 밖입니다. 이 PR에서 수정할 대상이 아닙니다." in reference
        assert "보고 심각도: 차단 → 참고" in reference
        assert "body unchanged_in_file" in reference
        assert "body outside_diff" in reference
        assert "body changed" not in reference
    assert "수정이 필요한 문제 1건" in publication
    assert "변경 범위 밖 참고 2건" in publication


def test_publication_synthesis_ok_still_renders_controller_reference_section() -> None:
    merged, outcome = _review()
    actionable = [
        group for group in merged.groups if group.effective_severity is not EffectiveSeverity.INFO
    ]
    synthesis = SynthesisDocument(
        overview="The changed code has actionable findings.",
        first_action="Address the changed code findings.",
        findings=[
            SynthesisFinding(
                key=group.key,
                title=f"Finding {group.key}",
                what="The changed code has a problem.",
                consequence="The behavior may be incorrect.",
                fix="Update the changed code.",
            )
            for group in actionable
        ],
    )
    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="en"),
        synthesis=synthesis,
    )
    assert "## Reference · Outside the change scope (existing code)" in body
    assert "This is outside this pull request's change scope" in body
    assert "Reported severity: Blocker → Info" in body


def test_publication_fallback_renders_same_controller_reference_section() -> None:
    merged, outcome = _review()
    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="en"),
    )
    assert "## Reference · Outside the change scope (existing code)" in body
    assert "This is outside this pull request's change scope" in body
    assert "Reported severity: Blocker → Info" in body


def test_demoted_groups_are_body_only_and_synthesis_receives_scope() -> None:
    merged, outcome = _review()
    inline = _confirmed_inline_groups(merged, outcome, PublishPolicy())
    assert all(group.effective_severity is not EffectiveSeverity.INFO for group in inline)
    assert {group.severity for group in inline} == {Severity.BLOCKER, Severity.WARNING}
    prompt = build_synthesis_prompt(
        target=_target(),
        merged=merged,
        outcome=outcome,
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale="ko"),
        budget_seconds=60,
    )
    assert "effective_severity: info" not in prompt
    assert "scope: outside_diff" not in prompt
    assert "demotion_reason: outside_diff" not in prompt
    assert "The supplied findings are the actionable candidate set" in prompt


def test_info_only_publish_payload_has_no_inline_comments_and_suppresses_synthesis_action(
    tmp_path,
) -> None:
    merged, outcome = _review()
    info_groups = [g for g in merged.groups if g.effective_severity is EffectiveSeverity.INFO]
    info_merged = merged.model_copy(update={"groups": info_groups})
    info_outcome = outcome.model_copy(
        update={
            "verdicts": {g.key: outcome.verdicts[g.key] for g in info_groups},
            "reasons": {g.key: outcome.reasons[g.key] for g in info_groups},
            "evidence": {g.key: outcome.evidence[g.key] for g in info_groups},
            "replica_votes": {g.key: outcome.replica_votes[g.key] for g in info_groups},
        }
    )
    run = RunStore(tmp_path).create(_target())
    run.save_synthesis(
        SynthesisDocument(
            overview="These blockers must be fixed before merging.",
            first_action="Fix the existing file immediately.",
            findings=[
                SynthesisFinding(
                    key=g.key,
                    title=f"title {g.key}",
                    what="existing behavior",
                    consequence="possible consequence",
                    fix="Fix this pull request.",
                )
                for g in info_groups
            ],
        )
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=1,
        report_md="",
        merged=info_merged,
        outcome=info_outcome,
        execute=False,
        locale="en",
    )
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert result.inline_count == 0
    assert "comments" not in payload
    assert "These blockers must be fixed" not in payload["body"]
    assert "Fix the existing file immediately" not in payload["body"]
    assert "Fix this pull request" not in payload["body"]
    assert payload["body"].count("This is outside this pull request's change scope") == 2
