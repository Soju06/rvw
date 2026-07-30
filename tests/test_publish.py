from __future__ import annotations

import json
from pathlib import Path

import pytest

import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding
from rvw.gate import (
    DispositionDecision,
    DispositionDocument,
    DispositionRecord,
    build_gate_verdict,
    render_gate_verdict,
)
from rvw.merge import MergeResult, merge
from rvw.publish import PublishError, publish_body_review, publish_review
from rvw.report import render_report
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunHandle, RunStore
from rvw.target import ResolvedTarget


def target_fixture() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py", "src/b.py", "src/c.py"],
        diff="",
        pr_number=42,
    )


def merged_fixture() -> MergeResult:
    findings = [
        EnrichedFinding(
            rule_id="rule/inline",
            file="src/a.py",
            hunk_id="a",
            line=10,
            severity=Severity.BLOCKER,
            body="INLINE-ONLY-BODY",
            anchorable=True,
            lane_id="lane",
            replica=1,
        ),
        EnrichedFinding(
            rule_id="rule/body",
            file="src/b.py",
            hunk_id="b",
            line=20,
            severity=Severity.WARNING,
            body="NON-ANCHORABLE-BODY",
            anchorable=False,
            lane_id="lane",
            replica=1,
        ),
        EnrichedFinding(
            rule_id="rule/rejected",
            file="src/c.py",
            hunk_id="c",
            line=30,
            severity=Severity.SUGGESTION,
            body="REJECTED-BODY",
            anchorable=True,
            lane_id="lane",
            replica=1,
        ),
    ]
    return merge(findings, lane_tiers={"lane": Tier.BASE})


def outcome_fixture(merged: MergeResult) -> AdjudicationOutcome:
    by_rule = {group.rule_id: group for group in merged.groups}
    verdicts = {
        by_rule["rule/inline"].key: Verdict.CONFIRMED,
        by_rule["rule/body"].key: Verdict.CONFIRMED,
        by_rule["rule/rejected"].key: Verdict.REJECTED,
    }
    return AdjudicationOutcome(
        verdicts=verdicts,
        reasons={key: f"reason {verdict.value}" for key, verdict in verdicts.items()},
        evidence={key: f"evidence {key}" for key in verdicts},
        replica_votes={key: [verdict] * 3 for key, verdict in verdicts.items()},
        unresolved=[],
        coerced_rejections=0,
    )


def prepared_run(tmp_path: Path) -> tuple[RunHandle, MergeResult, AdjudicationOutcome, str]:
    target = target_fixture()
    run = RunStore(tmp_path).create(target)
    merged = merged_fixture()
    outcome = outcome_fixture(merged)
    report = render_report(
        target=target,
        merged=merged,
        outcome=outcome,
        coverage=[],
        budget=None,
        synthesis="종합 본문",
    )
    return run, merged, outcome, report


def test_dry_run_writes_exact_split_payload_without_calling_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome, report = prepared_run(tmp_path)

    def forbidden_run(cmd: list[str], input_json: str) -> str:
        del cmd, input_json
        raise AssertionError("dry-run called gh")

    monkeypatch.setattr(publish_module, "_run", forbidden_run)

    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md=report,
        merged=merged,
        outcome=outcome,
        execute=False,
    )

    payload = json.loads((run.dir / "publish-payload.json").read_text(encoding="utf-8"))
    assert payload["event"] == "COMMENT"
    assert payload["body"].startswith("# rvw 리뷰")
    assert "종합 본문" in payload["body"]
    assert "NON-ANCHORABLE-BODY" in payload["body"]
    assert "INLINE-ONLY-BODY" not in payload["body"]
    assert len(payload["comments"]) == 1
    assert payload["comments"][0] == {
        "path": "src/a.py",
        "line": 10,
        "side": "RIGHT",
        "body": payload["comments"][0]["body"],
    }
    assert "INLINE-ONLY-BODY" in payload["comments"][0]["body"]
    assert result.review_url is None
    assert result.inline_count == 1
    assert result.body_fallback_count == 0
    assert result.state == "commented"


def test_execute_posts_comment_and_parses_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome, report = prepared_run(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], input_json: str) -> str:
        calls.append((cmd, json.loads(input_json)))
        return json.dumps({"html_url": "https://github.com/owner/repo/pull/42#pullrequestreview-1"})

    monkeypatch.setattr(publish_module, "_run", fake_run)

    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md=report,
        merged=merged,
        outcome=outcome,
        execute=True,
    )

    assert len(calls) == 1
    assert calls[0][0][-1] == "-"
    assert calls[0][1]["event"] == "COMMENT"
    assert result.review_url is not None
    assert result.review_url.endswith("pullrequestreview-1")
    assert result.inline_count == 1


def test_422_retries_once_with_all_inline_comments_in_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome, report = prepared_run(tmp_path)
    payloads: list[dict[str, object]] = []

    def fake_run(cmd: list[str], input_json: str) -> str:
        del cmd
        payloads.append(json.loads(input_json))
        if len(payloads) == 1:
            raise PublishError("anchor rejected", status_code=422)
        return json.dumps({"html_url": "https://example.test/review/2"})

    monkeypatch.setattr(publish_module, "_run", fake_run)

    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md=report,
        merged=merged,
        outcome=outcome,
        execute=True,
    )

    assert len(payloads) == 2
    assert payloads[0]["event"] == payloads[1]["event"] == "COMMENT"
    assert "comments" not in payloads[1]
    assert "### 앵커 실패 항목" in str(payloads[1]["body"])
    assert "INLINE-ONLY-BODY" in str(payloads[1]["body"])
    assert result.inline_count == 0
    assert result.body_fallback_count == 1


def test_non_422_error_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, merged, outcome, report = prepared_run(tmp_path)
    calls = 0

    def fake_run(cmd: list[str], input_json: str) -> str:
        nonlocal calls
        del cmd, input_json
        calls += 1
        raise PublishError("server failed", status_code=500)

    monkeypatch.setattr(publish_module, "_run", fake_run)

    with pytest.raises(PublishError, match="server failed"):
        publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md=report,
            merged=merged,
            outcome=outcome,
            execute=True,
        )

    assert calls == 1


def test_body_only_dry_run_writes_comment_payload_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_run(command: list[str], payload: str) -> str:
        raise AssertionError(f"dry-run called GitHub: {command} {payload}")

    monkeypatch.setattr(publish_module, "_run", forbidden_run)

    result = publish_body_review(
        run_dir=tmp_path,
        repo="owner/repo",
        pr_number=42,
        body="# stack report\n",
        execute=False,
    )

    payload = json.loads((tmp_path / "publish-payload.json").read_text(encoding="utf-8"))
    assert payload == {"body": "# stack report\n", "event": "COMMENT"}
    assert result.review_url is None
    assert result.inline_count == 0
    assert result.body_fallback_count == 0


def test_body_only_execute_makes_exactly_one_comment_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], payload: str) -> str:
        calls.append((command, json.loads(payload)))
        return json.dumps({"html_url": "https://github.com/owner/repo/pull/42#pullrequestreview-2"})

    monkeypatch.setattr(publish_module, "_run", fake_run)

    result = publish_body_review(
        run_dir=tmp_path,
        repo="owner/repo",
        pr_number=42,
        body="# stack report\n",
        execute=True,
    )

    assert len(calls) == 1
    assert calls[0][1] == {"body": "# stack report\n", "event": "COMMENT"}
    assert result.review_url is not None


def test_gate_verdict_uses_comment_only_bounded_fallback_and_keeps_dispositions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome, _ = prepared_run(tmp_path)
    document = DispositionDocument(
        schema_version=1,
        dispositions=[
            DispositionRecord(
                finding_id=group.key,
                decision=DispositionDecision.ACCEPTED,
                reason=f"accepted {group.rule_id}",
            )
            for group in merged.groups
            if outcome.verdicts[group.key] is Verdict.CONFIRMED
        ],
    )
    verdict = build_gate_verdict(
        run_id=run.run_id,
        target=target_fixture(),
        coverage=[],
        merged=merged,
        outcome=outcome,
        dispositions=document,
        actor="repo-owner",
        actor_permission="admin",
    )
    payloads: list[dict[str, object]] = []

    def fake_run(cmd: list[str], input_json: str) -> str:
        del cmd
        payloads.append(json.loads(input_json))
        if len(payloads) == 1:
            raise PublishError("anchor rejected", status_code=422)
        return json.dumps({"html_url": "https://example.test/review/gate"})

    monkeypatch.setattr(publish_module, "_run", fake_run)
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md=render_gate_verdict(verdict),
        merged=merged,
        outcome=outcome,
        execute=True,
    )

    assert len(payloads) == 2
    assert payloads[0]["event"] == payloads[1]["event"] == "COMMENT"
    assert "comments" not in payloads[1]
    assert "accepted rule/inline" in str(payloads[1]["body"])
    assert merged.groups[0].key in str(payloads[1]["body"])
    assert result.review_url == "https://example.test/review/gate"
