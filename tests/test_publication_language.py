"""The GitHub write seam gates all prose, including a possible anchor fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding
from rvw.langgate import check_language
from rvw.merge import merge
from rvw.presentation import PresentationConfig
from rvw.publication import evidence_fence
from rvw.publish import PublishError, publish_review
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunStore
from rvw.target import ResolvedTarget

ENGLISH = "An unchecked value reaches storage. Validate the value before saving it."
KOREAN = "잘못된 값이 저장 경로로 전달됩니다. 저장하기 전에 입력값을 검증하세요."
SOURCE = "save(unchecked_value)\n# quoted ``` source stays verbatim"


class FakeRewriter:
    def __init__(self, *, translate: bool = False, corrupt: bool = False) -> None:
        self.translate = translate
        self.corrupt = corrupt
        self.calls: list[tuple[str, ...]] = []

    async def rewrite(self, segments: tuple[str, ...], *, locale: str) -> list[str]:
        assert locale == "ko"
        self.calls.append(segments)
        if self.corrupt:
            return ["```\nchanged evidence\n```"] * len(segments)
        return [
            KOREAN if self.translate and not check_language(segment, "ko") else segment
            for segment in segments
        ]


def publication_input(tmp_path: Path):
    run = RunStore(tmp_path).create(
        ResolvedTarget(
            kind="pr",
            repo="owner/repo",
            pr_number=42,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_paths=["src/inline.py", "src/body.py"],
            diff="",
        )
    )
    presentation = PresentationConfig(locale="ko")
    run.save_presentation(presentation)
    merged = merge(
        [
            EnrichedFinding(
                rule_id=f"bori/{location}",
                file=f"src/{location}.py",
                line=12,
                hunk_id=location,
                severity=Severity.BLOCKER,
                body=ENGLISH,
                anchorable=location == "inline",
                lane_id="lane",
                replica=1,
            )
            for location in ["inline", "body"]
        ],
        lane_tiers={"lane": Tier.BASE},
    )
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
        reasons={group.key: ENGLISH for group in merged.groups},
        evidence={group.key: SOURCE for group in merged.groups},
        replica_votes={group.key: [Verdict.CONFIRMED] * 3 for group in merged.groups},
        unresolved=[],
        coerced_rejections=0,
    )
    run.save_merge(merged)
    run.save_outcome(outcome)
    run.save_report("DIAGNOSTIC REPORT MUST STAY UNCHANGED")
    return run, merged, outcome


@pytest.mark.parametrize("execute", [False, True])
def test_language_mismatch_prevents_every_github_write_and_dry_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, execute: bool
) -> None:
    run, merged, outcome = publication_input(tmp_path)
    fake = FakeRewriter()
    calls = []
    monkeypatch.setattr(publish_module, "_run", lambda *args: calls.append(args))
    with pytest.raises(PublishError) as raised:
        publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md="diagnostic",
            merged=merged,
            outcome=outcome,
            execute=execute,
            rewriter=fake,
        )
    assert getattr(raised.value, "reason", None) == "publication_language_mismatch"
    assert len(fake.calls) == 1
    assert calls == []
    assert not (run.dir / "publish-payload.json").exists()


def test_one_rewrite_covers_body_inline_and_422_fallback_without_changing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = publication_input(tmp_path)
    fake = FakeRewriter(translate=True)
    payloads = []
    before_merge = run.load_merge().model_dump_json()
    before_outcome = run.load_outcome().model_dump_json()

    def gh(cmd: list[str], input_json: str) -> str:
        payloads.append(json.loads(input_json))
        if len(payloads) == 1:
            raise PublishError("invalid anchor", status_code=422)
        return json.dumps({"html_url": "https://example.test/review"})

    monkeypatch.setattr(publish_module, "_run", gh)
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="diagnostic",
        merged=merged,
        outcome=outcome,
        execute=True,
        rewriter=fake,
    )
    assert len(fake.calls) == 1
    assert len(payloads) == 2
    assert result.body_fallback_count == 1
    assert not result.language_fallback_used
    # Every finding remains in both body variants, and the inline finding also
    # appears in the inline comment and appended 422 fallback section.
    assert fake.calls[0].count(ENGLISH) == 6
    supplied = "".join(fake.calls[0])
    for protected in [SOURCE, "bori/inline", "bori/body", "src/inline.py:12", "차단"]:
        assert protected not in supplied
    first, fallback = payloads
    assert len(first["comments"]) == 1
    assert "comments" not in fallback
    comment = first["comments"][0]
    assert (comment["path"], comment["line"], comment["side"]) == ("src/inline.py", 12, "RIGHT")
    for body in [first["body"], comment["body"], fallback["body"]]:
        assert check_language(body, "ko")
        assert ENGLISH not in body
        assert evidence_fence(SOURCE) in body
    assert fallback["body"].count(evidence_fence(SOURCE)) == 3
    assert fallback["body"].count("`bori/inline`") == 2
    assert fallback["body"].count("`bori/body`") == 1
    assert run.load_merge().model_dump_json() == before_merge
    assert run.load_outcome().model_dump_json() == before_outcome
    assert run.load_report() == "DIAGNOSTIC REPORT MUST STAY UNCHANGED"


@pytest.mark.parametrize("corrupt", [False, True])
def test_explicit_language_fallback_records_use_and_publishes_original_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt: bool
) -> None:
    run, merged, outcome = publication_input(tmp_path)
    fake = FakeRewriter(corrupt=corrupt)
    payloads = []

    def gh(cmd: list[str], input_json: str) -> str:
        payloads.append(json.loads(input_json))
        return json.dumps({"html_url": "https://example.test/review"})

    monkeypatch.setattr(publish_module, "_run", gh)
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="diagnostic",
        merged=merged,
        outcome=outcome,
        execute=True,
        rewriter=fake,
        allow_language_fallback=True,
    )
    assert len(fake.calls) == 1
    assert len(payloads) == 1
    assert result.language_fallback_used
    assert ENGLISH in payloads[0]["body"]
    assert "changed evidence" not in json.dumps(payloads[0])
    assert evidence_fence(SOURCE) in payloads[0]["comments"][0]["body"]


def test_matching_publication_never_invokes_rewriter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = publication_input(tmp_path)
    merged = merged.model_copy(
        update={
            "groups": [group.model_copy(update={"bodies": [KOREAN]}) for group in merged.groups]
        }
    )
    outcome = outcome.model_copy(update={"reasons": dict.fromkeys(outcome.reasons, KOREAN)})
    fake = FakeRewriter()
    monkeypatch.setattr(
        publish_module, "_run", lambda *_: pytest.fail("dry-run must never call GitHub")
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="diagnostic",
        merged=merged,
        outcome=outcome,
        execute=False,
        rewriter=fake,
    )
    assert fake.calls == []
    assert not result.language_fallback_used
    assert (run.dir / "publish-payload.json").exists()


def test_degraded_korean_review_publishes_without_rewrite_because_lane_ids_are_protected(
    tmp_path: Path,
) -> None:
    """The failed-lanes sentence names Latin lane ids; publish_review must protect them itself."""
    from rvw.discover import DiscoverResult, LaneCoverage, RunCoverage
    from rvw.langgate import check_language

    class NeverRewriter:
        async def rewrite(self, segments: tuple[str, ...], *, locale: str) -> list[str]:
            raise AssertionError(f"rewrite must not run for {locale}: {segments}")

    run = RunStore(tmp_path).create(
        ResolvedTarget(
            kind="pr",
            repo="owner/repo",
            pr_number=1744,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_paths=["src/app.py"],
            diff="",
        )
    )
    run.save_presentation(PresentationConfig(locale="ko"))
    dead_lanes = ["correctness", "hygiene", "contracts", "security-exposure", "ci-integrity"]
    run.save_discover(
        DiscoverResult(
            lane_results={},
            findings=[],
            coverage=[
                LaneCoverage(
                    lane_id=lane_id,
                    dispatched=1,
                    valid=0,
                    findings=0,
                    runs=[
                        RunCoverage(
                            replica=1,
                            chunk=1,
                            valid=False,
                            findings=0,
                            invalid_reason="exit_nonzero:124",
                        )
                    ],
                    redispatch_skipped="dead_by_timeout",
                    uncovered=["src/app.py@@-0,0+1,2@@"],
                )
                for lane_id in dead_lanes
            ],
        )
    )
    merged = merge([], lane_tiers={})
    run.save_merge(merged)
    run.save_report("DIAGNOSTIC REPORT MUST STAY UNCHANGED")

    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=1744,
        report_md="",
        merged=merged,
        outcome=None,
        execute=False,
        rewriter=NeverRewriter(),
    )

    assert result.language_fallback_used is False
    body = json.loads((run.dir / "publish-payload.json").read_text(encoding="utf-8"))["body"]
    assert f"검토를 완료하지 못한 규칙 묶음 5개: {', '.join(dead_lanes)}." in body
    # Protection is load-bearing: unprotected, five Latin ids fail the Korean threshold.
    assert not check_language(body, "ko")
    assert check_language(body, "ko", protected_literals=dead_lanes)
    facts = json.loads((run.dir / "publication.json").read_text(encoding="utf-8"))
    assert facts == {
        "publication_failure": None,
        "language_fallback_used": False,
        "rewrite_attempted": False,
    }
