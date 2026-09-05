from __future__ import annotations

import json
from pathlib import Path

from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import DiffBudgetReport, DiffChunkPlacement
from rvw.discover import EnrichedFinding, LaneCoverage, RunCoverage
from rvw.merge import MergeResult, merge
from rvw.report import render_report
from rvw.schema import Severity, Tier, Verdict
from rvw.target import ResolvedTarget

FIXTURES = Path(__file__).parent / "fixtures"


def outcome_from_fixture() -> AdjudicationOutcome:
    raw = json.loads((FIXTURES / "smoke_1119_outcome.json").read_text(encoding="utf-8"))
    return AdjudicationOutcome(
        verdicts={key: Verdict(value) for key, value in raw["verdicts"].items()},
        reasons=raw["reasons"],
        evidence=raw["evidence"],
        replica_votes={
            key: [Verdict(value) for value in votes] for key, votes in raw["replica_votes"].items()
        },
        unresolved=raw["unresolved"],
        coerced_rejections=raw["coerced_rejections"],
    )


def merged_from_fixture() -> MergeResult:
    raw = json.loads((FIXTURES / "smoke_1119_findings.json").read_text(encoding="utf-8"))
    findings = [EnrichedFinding.model_validate(item) for item in raw]
    tiers = {
        finding.lane_id: (Tier.DYNAMIC if finding.lane_id.startswith("dynamic/") else Tier.BASE)
        for finding in findings
    }
    return merge(findings, lane_tiers=tiers)


def target_fixture() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="APIFuseHQ/apifuse",
        base_sha="a" * 40,
        head_sha="b5b9a7c8a" + "0" * 31,
        changed_paths=[],
        diff="",
        pr_number=1119,
    )


def coverage_fixture(
    lane_id: str,
    *,
    valid: int,
    findings: int,
    replicas: int = 3,
) -> LaneCoverage:
    runs = [
        RunCoverage(
            replica=replica,
            chunk=1,
            valid=replica <= valid,
            findings=findings if replica == 1 else 0,
            invalid_reason=None if replica <= valid else "scripted_invalid",
        )
        for replica in range(1, replicas + 1)
    ]
    return LaneCoverage(
        lane_id=lane_id,
        dispatched=replicas,
        valid=valid,
        findings=findings,
        runs=runs,
    )


def render_real(*, synthesis: str | None = None) -> str:
    return render_report(
        target=target_fixture(),
        merged=merged_from_fixture(),
        outcome=outcome_from_fixture(),
        coverage=[
            coverage_fixture("slop-hygiene", valid=3, findings=7),
            coverage_fixture("unscoped-sweep", valid=2, findings=4),
        ],
        budget=DiffBudgetReport(
            kept_files=["a.ts"],
            excluded_files=["generated.ts", "bun.lockb"],
            excluded_reason={
                "generated.ts": "generated-path",
                "bun.lockb": "generated-path",
            },
            kept_chars=12345,
            excluded_chars=6789,
            chunk_count=1,
            chunks=[DiffChunkPlacement(index=1, files=["a.ts"], chars=12345)],
        ),
        synthesis=synthesis,
    )


def test_real_report_order_folds_regions_coverage_and_empty_sections() -> None:
    report = render_real()

    headings = [
        "# rvw 리뷰 — APIFuseHQ/apifuse PR#1119",
        "## 종합",
        "## 확정 발견 (CONFIRMED)",
        "## 커버리지",
    ]
    positions = [report.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "head: `b5b9a7c8a" in report
    assert "UTC" in report
    assert report.count("### slop/sot-violation — 4개 위치 (반복 패턴)") == 1
    assert report.count("- `providers/") >= 4
    assert "공유 식별자: `errorCodes`" in report
    assert "(인접: providers/naver-map/index.ts L1721\N{EN DASH}1733)" in report
    assert "| 합계 | 6 | 5 | 11 | 0 |" in report
    assert "diff 예산: 12,345자 유지 / 6,789자 제외 (generated.ts, bun.lockb)" in report
    assert "1청크" in report
    assert "## 기각 (REJECTED)" not in report
    assert "## 검증 미확정" not in report


def test_agentic_report_surfaces_uncovered_hunks_without_budget() -> None:
    lane = coverage_fixture("agentic-lane", valid=3, findings=0).model_copy(
        update={
            "coverage_redispatched": True,
            "uncovered": ["src/a.py@@-1,1+1,2@@"],
        }
    )

    report = render_report(
        target=target_fixture(),
        merged=merge([], lane_tiers={}),
        outcome=None,
        coverage=[lane],
        budget=None,
    )

    assert "| 레인 | 발사 | 유효 | 발견 | 미커버 |" in report
    assert "| agentic-lane | 3 | 3 | 0 | 1 |" in report
    assert "- `agentic-lane`: `src/a.py@@-1,1+1,2@@`" in report
    assert "diff 예산:" not in report


def test_synthesis_placeholder_and_verbatim_injection() -> None:
    placeholder = render_real()
    synthesis = "첫 문단입니다.\n\n- 그대로 유지\n"
    injected = render_real(synthesis=synthesis)

    assert "_(종합은 오케스트레이터가 작성합니다 — rvw report --synthesis 로 주입)_" in placeholder
    assert synthesis in injected
    assert "종합은 오케스트레이터" not in injected


def _synthetic_merged() -> MergeResult:
    findings = [
        EnrichedFinding(
            rule_id=f"rule/{index}",
            file="src/app.py",
            hunk_id=f"h{index}",
            line=10 + index,
            severity=Severity.WARNING,
            body=f"body {index}",
            anchorable=True,
            lane_id="lane",
            replica=1,
        )
        for index in range(3)
    ]
    return merge(findings, lane_tiers={"lane": Tier.BASE})


def _pattern_merged(*, bodies: tuple[str, str]) -> MergeResult:
    findings = [
        EnrichedFinding(
            rule_id="test-ci/critical-flaw",
            file=file,
            hunk_id=f"{file}@@-1,1+1,1@@",
            line=line,
            severity=Severity.WARNING,
            body=body,
            anchorable=True,
            lane_id="test-ci-integrity",
            replica=1,
        )
        for file, line, body in zip(("a.ts", "b.ts"), (10, 20), bodies, strict=True)
    ]
    return merge(findings, lane_tiers={"test-ci-integrity": Tier.BASE})


def _confirmed_outcome(
    *,
    reasons: dict[str, str],
    evidence: dict[str, str],
) -> AdjudicationOutcome:
    return AdjudicationOutcome(
        verdicts=dict.fromkeys(reasons, Verdict.CONFIRMED),
        reasons=reasons,
        evidence=evidence,
        replica_votes={key: [Verdict.CONFIRMED] * 3 for key in reasons},
        unresolved=[],
        coerced_rejections=0,
    )


def test_report_uses_discovery_replica_count_for_ordinary_item() -> None:
    # Given a finding from a run configured with one discovery replica.
    merged = _synthetic_merged()
    group = merged.groups[0]
    outcome = _confirmed_outcome(
        reasons={group.key: "confirmed"},
        evidence={group.key: "evidence"},
    )

    # When the report is rendered from persisted discovery coverage.
    report = render_report(
        target=target_fixture(),
        merged=merged,
        outcome=outcome,
        coverage=[coverage_fixture("lane", valid=1, findings=3, replicas=1)],
        budget=None,
    )

    # Then the agreement denominator describes discovery, not adjudication.
    assert "복제 동의 1/1 · 판정 CONFIRMED/CONFIRMED/CONFIRMED" in report
    assert "복제 동의 1/3" not in report


def test_report_uses_discovery_replica_count_for_pattern_fold() -> None:
    # Given a repeated pattern from a run configured with two discovery replicas.
    merged = _pattern_merged(bodies=("shared `value`", "shared `value`"))

    # When the pattern fold is rendered from persisted discovery coverage.
    report = render_report(
        target=target_fixture(),
        merged=merged,
        outcome=None,
        coverage=[coverage_fixture("test-ci-integrity", valid=2, findings=2, replicas=2)],
        budget=None,
    )

    # Then its denominator is the configured discovery count.
    assert "### test-ci/critical-flaw — 2개 위치 (반복 패턴)" in report
    assert "복제 동의 1/2 · 판정 미판정" in report
    assert "복제 동의 1/3" not in report


def test_pattern_fold_renders_each_member_when_reasons_differ() -> None:
    merged = _pattern_merged(
        bodies=("representative A with `shared`", "representative B with `shared`")
    )
    by_file = {group.file: group for group in merged.groups}
    outcome = _confirmed_outcome(
        reasons={
            by_file["a.ts"].key: "first reason",
            by_file["b.ts"].key: " second reason ",
        },
        evidence={by_file["a.ts"].key: "first evidence", by_file["b.ts"].key: ""},
    )

    report = render_report(
        target=target_fixture(), merged=merged, outcome=outcome, coverage=[], budget=None
    )

    first = "**a.ts:10** — first reason"
    second = "**b.ts:20** — second reason"
    assert first in report
    assert second in report
    assert report.index(first) < report.index(second)
    assert "first evidence" in report
    assert report.count("```") == 2
    assert "representative A" not in report
    assert "representative B" not in report


def test_pattern_fold_renders_one_reason_when_all_members_match() -> None:
    merged = _pattern_merged(
        bodies=("representative A with `shared`", "representative B with `shared`")
    )
    by_file = {group.file: group for group in merged.groups}
    outcome = _confirmed_outcome(
        reasons={
            by_file["a.ts"].key: " same reason ",
            by_file["b.ts"].key: "same reason",
        },
        evidence={by_file["a.ts"].key: "shared evidence", by_file["b.ts"].key: ""},
    )

    report = render_report(
        target=target_fixture(), merged=merged, outcome=outcome, coverage=[], budget=None
    )

    assert report.count("판정 사유: same reason") == 1
    assert "**a.ts:10** —" not in report
    assert "**b.ts:20** —" not in report


def test_unadjudicated_pattern_fold_renders_differing_member_bodies() -> None:
    merged = _pattern_merged(bodies=("first body `shared`", "second body `shared`"))

    report = render_report(
        target=target_fixture(), merged=merged, outcome=None, coverage=[], budget=None
    )

    first = "**a.ts:10** — first body `shared`"
    second = "**b.ts:20** — second body `shared`"
    assert first in report
    assert second in report
    assert report.index(first) < report.index(second)
    assert report.count("### test-ci/critical-flaw — 2개 위치 (반복 패턴)") == 1


def test_rejected_unresolved_and_unadjudicated_modes() -> None:
    merged = _synthetic_merged()
    confirmed, rejected, uncertain = merged.groups
    outcome = AdjudicationOutcome(
        verdicts={
            confirmed.key: Verdict.CONFIRMED,
            rejected.key: Verdict.REJECTED,
            uncertain.key: Verdict.UNCERTAIN,
        },
        reasons={
            confirmed.key: "confirmed reason",
            rejected.key: "rejected reason",
            uncertain.key: "uncertain reason",
        },
        evidence={
            confirmed.key: "confirmed evidence",
            rejected.key: "rejecting evidence",
            uncertain.key: "uncertain evidence",
        },
        replica_votes={
            confirmed.key: [Verdict.CONFIRMED] * 3,
            rejected.key: [Verdict.REJECTED] * 3,
            uncertain.key: [Verdict.UNCERTAIN] * 3,
        },
        unresolved=[uncertain.key],
        coerced_rejections=2,
    )

    adjudicated = render_report(
        target=target_fixture(),
        merged=merged,
        outcome=outcome,
        coverage=[],
        budget=None,
    )
    unadjudicated = render_report(
        target=target_fixture(),
        merged=merged,
        outcome=None,
        coverage=[],
        budget=None,
    )

    assert "## 검증 미확정" in adjudicated
    assert "확장 컨텍스트 재검증에서도 미확정 — 수동 확인 필요" in adjudicated
    assert "## 기각 (REJECTED)" in adjudicated
    assert "<details>" in adjudicated
    assert "rejecting evidence" in adjudicated
    assert "근거 없는 기각 교정: 2건" in adjudicated
    assert "## 발견 (미판정)" in unadjudicated
    assert "## 확정 발견 (CONFIRMED)" not in unadjudicated
