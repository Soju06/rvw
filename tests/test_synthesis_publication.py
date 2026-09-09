from __future__ import annotations

import json
from pathlib import Path

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding
from rvw.langgate import check_language
from rvw.merge import MergeResult, merge
from rvw.presentation import PresentationConfig
from rvw.publication import render_publication, render_publication_item
from rvw.publish import publish_review
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunStore
from rvw.synthesis import SynthesisDocument
from rvw.target import ResolvedTarget

FIXTURE = Path(__file__).parent / "fixtures" / "bori_1800_publication.json"


def _review() -> tuple[MergeResult, AdjudicationOutcome]:
    findings = [
        EnrichedFinding(
            rule_id="test-ci/critical-flaw",
            file="apps/api/src/user.test.ts",
            hunk_id="user-test",
            line=67,
            severity=Severity.BLOCKER,
            body="dense blocker body",
            anchorable=True,
            lane_id="test-ci-integrity",
            replica=1,
        ),
        EnrichedFinding(
            rule_id="contracts/error-shape",
            file="apps/api/src/handler.ts",
            hunk_id="handler",
            line=91,
            severity=Severity.WARNING,
            body="dense warning body",
            anchorable=False,
            lane_id="contracts",
            replica=1,
        ),
    ]
    merged = merge(findings, lane_tiers={"test-ci-integrity": Tier.BASE, "contracts": Tier.BASE})
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
        reasons={
            group.key: f"Confirmed: duplicate reason for {group.rule_id}" for group in merged.groups
        },
        evidence={
            group.key: (
                "findUnique({ where: { id: userId } })"
                if group.rule_id == "test-ci/critical-flaw"
                else 'throw new ApiError("USER_NOT_FOUND")'
            )
            for group in merged.groups
        },
        replica_votes={group.key: [Verdict.CONFIRMED] * 3 for group in merged.groups},
        unresolved=[],
        coerced_rejections=0,
    )
    return merged, outcome


def _synthesis(merged: MergeResult, *, locale: str = "en") -> SynthesisDocument:
    prose = {
        "en": {
            "overview": "This pull request strengthens user lookup tests. One test still accepts the wrong user.",
            "first_action": "Make the database double respond to the requested user ID first.",
            "items": [
                (
                    "The test passes when the wrong user is queried",
                    "The `apps/api/src/user.test.ts` database double returns the same fixture for every `findUnique` call.",
                    "A query for another user can pass this test.",
                    "Make the double return a result based on `userId` and add a mismatch case.",
                ),
                (
                    "The handler exposes the wrong error shape",
                    "`apps/api/src/handler.ts` calls `handleUser`, which raises `ApiError` without the documented code.",
                    "Clients cannot distinguish `USER_NOT_FOUND` from other failures.",
                    "Set the documented `USER_NOT_FOUND` code at the throw site.",
                ),
            ],
        },
        "ko": {
            "overview": "이 변경은 사용자 조회 테스트를 보강합니다. 한 테스트는 여전히 잘못된 사용자를 허용합니다.",
            "first_action": "먼저 데이터베이스 대역이 요청받은 사용자 ID에 맞게 응답하도록 수정해야 합니다.",
            "items": [
                (
                    "잘못된 사용자를 조회해도 테스트가 통과합니다",
                    "`apps/api/src/user.test.ts`의 데이터베이스 대역은 모든 `findUnique` 호출에 같은 값을 반환합니다.",
                    "다른 사용자를 조회하는 구현도 이 테스트를 통과할 수 있습니다.",
                    "대역이 `userId`에 맞는 결과를 반환하게 하고 불일치 사례를 추가해야 합니다.",
                ),
                (
                    "처리기가 잘못된 오류 형태를 노출합니다",
                    "`apps/api/src/handler.ts`의 `handleUser`는 문서에 정한 코드 없이 `ApiError`를 발생시킵니다.",
                    "클라이언트가 `USER_NOT_FOUND`를 다른 실패와 구분할 수 없습니다.",
                    "오류 발생 지점에 문서에 정한 `USER_NOT_FOUND` 코드를 넣어야 합니다.",
                ),
            ],
        },
    }[locale]
    return SynthesisDocument.model_validate(
        {
            "overview": prose["overview"],
            "first_action": prose["first_action"],
            "findings": [
                {
                    "key": group.key,
                    "title": item[0],
                    "what": item[1],
                    "consequence": item[2],
                    "fix": item[3],
                }
                for group, item in zip(merged.groups, prose["items"], strict=True)
            ],
        }
    )


def test_synthesized_publication_leads_with_purpose_and_keeps_inline_synopsis() -> None:
    merged, outcome = _review()
    synthesis = _synthesis(merged)
    inline = next(group for group in merged.groups if group.anchorable)
    body_only = next(group for group in merged.groups if not group.anchorable)

    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="en"),
        synthesis=synthesis,
        inline_keys=frozenset({inline.key}),
    )

    assert body.startswith(f"{synthesis.overview} {synthesis.first_action}\n\nReview complete.")
    assert body.count("The test passes when the wrong user is queried") == 1
    assert "`apps/api/src/user.test.ts:67` · **Blocker** · `test-ci/critical-flaw`" in body
    assert "A query for another user can pass this test." in body
    assert "The database double returns" not in body
    assert "Make the double return" not in body
    assert "findUnique({ where: { id: userId } })" not in body

    full = next(item for item in synthesis.findings if item.key == body_only.key)
    for text in (full.title, full.what, full.consequence, full.fix):
        assert text in body
    assert "Confirmed:" not in body
    assert "<summary>Evidence</summary>" in body
    assert 'throw new ApiError("USER_NOT_FOUND")' in body
    assert "None." not in body


def test_synthesized_inline_item_has_full_explanation_collapsed_evidence() -> None:
    merged, outcome = _review()
    synthesis = _synthesis(merged)
    group = next(group for group in merged.groups if group.anchorable)

    item = render_publication_item(
        group,
        outcome,
        presentation=PresentationConfig(locale="en"),
        synthesis=synthesis,
        inline=True,
    )

    finding = next(item for item in synthesis.findings if item.key == group.key)
    assert item.startswith(f"### {finding.title}")
    for text in (finding.what, finding.consequence, finding.fix):
        assert text in item
    assert "Confirmed:" not in item
    assert "<details>" in item and "<summary>Evidence</summary>" in item
    assert item.endswith("</details>")


def test_synthesis_order_applies_within_each_severity_section() -> None:
    merged, outcome = _review()
    groups = [group.model_copy(update={"severity": Severity.BLOCKER}) for group in merged.groups]
    merged = merged.model_copy(update={"groups": groups})
    synthesis = _synthesis(merged).model_copy(
        update={"findings": list(reversed(_synthesis(merged).findings))}
    )

    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="en"),
        synthesis=synthesis,
    )

    assert body.index(synthesis.findings[0].title) < body.index(synthesis.findings[1].title)


def test_fallback_publication_retains_inline_findings_and_empty_only_for_zero() -> None:
    merged, outcome = _review()
    inline = next(group for group in merged.groups if group.anchorable)

    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="en"),
        inline_keys=frozenset({inline.key}),
    )

    assert "dense blocker body" in body
    assert "dense warning body" in body
    assert "## Changes required\n\nNone." not in body
    assert "## Needs attention\n\nNone." not in body

    empty = render_publication(
        merged=merge([], lane_tiers={}),
        outcome=None,
        presentation=PresentationConfig(locale="en"),
    )
    assert "## Changes required\n\nNone." in empty
    assert "## Needs attention\n\nNone." in empty


def test_korean_synthesis_preserves_english_literals_through_language_gate() -> None:
    merged, outcome = _review()
    synthesis = _synthesis(merged, locale="ko")
    inline = next(group for group in merged.groups if group.anchorable)
    body = render_publication(
        merged=merged,
        outcome=outcome,
        presentation=PresentationConfig(locale="ko"),
        synthesis=synthesis,
        inline_keys=frozenset({inline.key}),
    )
    item = render_publication_item(
        inline,
        outcome,
        presentation=PresentationConfig(locale="ko"),
        synthesis=synthesis,
        inline=True,
    )

    protected = [
        "apps/api/src/user.test.ts",
        "apps/api/src/handler.ts",
        "findUnique",
        "userId",
        "handleUser",
        "ApiError",
        "USER_NOT_FOUND",
    ]
    assert check_language(body, "ko", protected_literals=protected)
    assert check_language(item, "ko", protected_literals=protected)
    for literal in protected:
        if literal in body or literal in item:
            assert literal.encode() in (body + item).encode()


def test_publish_loads_korean_synthesis_and_keeps_inline_marker_last(tmp_path: Path) -> None:
    class NeverRewriter:
        async def rewrite(self, segments: tuple[str, ...], *, locale: str) -> list[str]:
            raise AssertionError(f"unexpected rewrite for {locale}: {segments}")

    merged, outcome = _review()
    synthesis = _synthesis(merged, locale="ko")
    run = RunStore(tmp_path).create(
        ResolvedTarget(
            kind="pr",
            repo="owner/repo",
            pr_number=1800,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_paths=[group.file for group in merged.groups],
            diff="",
        )
    )
    run.save_presentation(PresentationConfig(locale="ko"))
    run.save_merge(merged)
    run.save_outcome(outcome)
    run.save_synthesis(synthesis)
    assert run.load_synthesis() == synthesis

    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=1800,
        report_md="diagnostic",
        merged=merged,
        outcome=outcome,
        execute=False,
        rewriter=NeverRewriter(),
    )

    payload = json.loads((run.dir / "publish-payload.json").read_text(encoding="utf-8"))
    assert result.inline_count == 1
    comment = payload["comments"][0]["body"]
    assert "<summary>근거 보기</summary>" in comment
    assert "Confirmed:" not in comment
    assert comment.rstrip().endswith("-->")
    assert comment.rfind("</details>") < comment.rfind("<!-- rvw:v1")
    assert "잘못된 사용자를 조회해도 테스트가 통과합니다" in payload["body"]
    assert "다른 사용자를 조회하는 구현도" in payload["body"]
    assert "데이터베이스 대역은 모든" not in payload["body"]


def test_bori_1800_persisted_fixture_shows_reader_first_before_after(tmp_path: Path) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    finding = raw["finding"]
    merged = merge(
        [
            EnrichedFinding(
                rule_id=finding["rule_id"],
                file=finding["file"],
                hunk_id=finding["hunk_id"],
                line=finding["line"],
                severity=finding["severity"],
                body=finding["original_body_ko"],
                anchorable=True,
                lane_id="test-ci-integrity",
                replica=1,
            )
        ],
        lane_tiers={"test-ci-integrity": Tier.BASE},
    )
    group = merged.groups[0]
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED},
        reasons={group.key: raw["adjudication"]["reason_ko"]},
        evidence={group.key: raw["adjudication"]["evidence"]},
        replica_votes={group.key: [Verdict.CONFIRMED] * 3},
        unresolved=[],
        coerced_rejections=0,
    )
    synthesis = SynthesisDocument.model_validate(
        {
            "overview": raw["synthesis"]["overview"],
            "first_action": raw["synthesis"]["first_action"],
            "findings": [
                {
                    "key": group.key,
                    **{k: raw["synthesis"][k] for k in ("title", "what", "consequence", "fix")},
                }
            ],
        }
    )
    run = RunStore(tmp_path).create(
        ResolvedTarget(
            kind="pr",
            repo="fixture/bori",
            pr_number=1800,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_paths=[group.file],
            diff="",
        )
    )
    run.save_merge(merged)
    run.save_outcome(outcome)
    run.save_synthesis(synthesis)
    merged = run.load_merge()
    outcome = run.load_outcome()
    synthesis = run.load_synthesis()
    assert synthesis is not None
    group = merged.groups[0]

    before = render_publication_item(
        group, outcome, presentation=PresentationConfig(locale="ko"), inline=True
    )
    after = render_publication_item(
        group,
        outcome,
        presentation=PresentationConfig(locale="ko"),
        synthesis=synthesis,
        inline=True,
    )

    assert before.startswith("**차단 · `test-ci/critical-flaw`**")
    assert "Confirmed:" in before
    assert after.startswith("### 잘못된 사용자를 조회해도 테스트가 통과합니다")
    assert "Confirmed:" not in after
    assert "구현이 다른 사용자 ID를 조회해도" in after
    assert "<details>" in after
