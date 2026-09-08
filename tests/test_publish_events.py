"""The review event follows repository policy; idempotent per head; dismissal is own-only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_publish_threads import (
    BOT,
    H1,
    H2,
    PR_PATH,
    REVIEWS_PATH,
    FakeGitHub,
    comments_of,
    github_with,
    post_recorder,
    prepared_run,
    writes,
)

import rvw.cli as cli_module
import rvw.publish as publish_module
from rvw.policy import EffectivePolicy, PublishPolicy, validate_policy
from rvw.publish import EventOverrideRejected, PublishError, publish_review, select_event
from rvw.store import RunStore
from rvw.summary import ExecutionSummary
from rvw.target import ResolvedTarget
from rvw.threads import ReviewEvent, build_review_marker

REQUEST_CHANGES = PublishPolicy(on_block="request_changes")
APPROVE = PublishPolicy(on_pass="approve", approve_requires_explicit_opt_in=False)
NONE = PublishPolicy(on_pass="none")
DISMISS = PublishPolicy(on_block="request_changes", dismiss_on_pass=True)


@pytest.mark.parametrize(
    ("policy", "verdict", "clamp", "has_prose", "expected"),
    [
        (PublishPolicy(), "BLOCK", False, True, "COMMENT"),
        (PublishPolicy(), "PASS", False, True, "COMMENT"),
        (REQUEST_CHANGES, "BLOCK", False, True, "REQUEST_CHANGES"),
        (REQUEST_CHANGES, "PASS", False, True, "COMMENT"),
        (APPROVE, "PASS", False, False, "APPROVE"),
        (APPROVE, "PASS", False, True, "APPROVE"),
        (APPROVE, "BLOCK", False, True, "COMMENT"),
        (NONE, "PASS", False, False, None),
        (NONE, "PASS", False, True, "COMMENT"),
        (NONE, "BLOCK", False, True, "COMMENT"),
        (REQUEST_CHANGES, "BLOCK", True, True, "COMMENT"),
        (APPROVE, "PASS", True, False, "COMMENT"),
        (NONE, "PASS", True, False, "COMMENT"),
        (REQUEST_CHANGES, None, False, True, "COMMENT"),
        (APPROVE, None, False, True, "COMMENT"),
    ],
)
def test_select_event_matrix(policy, verdict, clamp, has_prose, expected) -> None:
    assert select_event(policy, verdict, clamp=clamp, has_prose=has_prose) == expected


def own_review(
    review_id: int,
    *,
    head: str,
    event: ReviewEvent,
    state: str | None = None,
    login: str = "review-bot[bot]",
    kind: str = "Bot",
    marked: bool = True,
) -> dict[str, object]:
    states = {"COMMENT": "COMMENTED", "REQUEST_CHANGES": "CHANGES_REQUESTED", "APPROVE": "APPROVED"}
    body = "## Summary\n\nbody\n\n" + (
        build_review_marker(head_sha=head, event=event) if marked else ""
    )  # type: ignore[arg-type]
    return {
        "id": review_id,
        "state": state or states[event],
        "body": body,
        "user": {"login": login, "type": kind},
    }


def test_block_with_request_changes_policy_posts_request_changes_pinned_to_the_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    github = github_with(
        [
            {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            }
        ]
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "REQUEST_CHANGES" and payloads[0]["commit_id"] == H2
    assert (
        str(payloads[0]["body"])
        .rstrip()
        .endswith(f"<!-- rvw:v1 review head={H2} event=REQUEST_CHANGES -->")
    )
    assert result.state == "changes_requested" and result.event == "REQUEST_CHANGES"
    assert result.facts is not None
    assert result.facts.event == "REQUEST_CHANGES" and result.facts.policy_source == "repository"
    assert result.facts.event_clamped_reason is None
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publish.event == "REQUEST_CHANGES" and summary.publication_skipped is None


def test_pass_with_opted_in_approve_carries_the_body_only_when_there_is_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="PASS",
        publish_policy=APPROVE,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "APPROVE" and len(comments_of(payloads[0])) == 3
    assert str(payloads[0]["body"]).startswith("## Summary")
    assert result.state == "approved"
    # no findings at all: APPROVE without body prose, only the review marker
    clean_run, clean_merged, clean_outcome = prepared_run(tmp_path / "clean", empty=True)
    payloads.clear()
    publish_review(
        run=clean_run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=clean_merged,
        outcome=clean_outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="PASS",
        publish_policy=APPROVE,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "APPROVE" and "comments" not in payloads[0]
    assert payloads[0]["body"] == build_review_marker(head_sha=H2, event="APPROVE")


def empty_threads() -> dict[str, object]:
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                }
            }
        }
    }


def test_pass_with_none_posts_no_review_when_there_is_nothing_to_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)
    calls: list[str] = []
    post_recorder(monkeypatch, calls)
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="PASS",
        publish_policy=NONE,
        policy_source="repository",
    )
    assert calls == [] and result.state == "skipped" and result.skipped == "on_pass_none"
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publication_skipped == "on_pass_none" and summary.publish.event is None
    # with findings to show it degrades to a COMMENT
    run2, merged2, outcome2 = prepared_run(tmp_path / "prose")
    payloads = post_recorder(monkeypatch, calls)
    result = publish_review(
        run=run2,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged2,
        outcome=outcome2,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="PASS",
        publish_policy=NONE,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "COMMENT" and result.event == "COMMENT"


@pytest.mark.parametrize("policy", [REQUEST_CHANGES, APPROVE])
def test_degraded_runs_never_escalate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: PublishPolicy
) -> None:
    run, merged, outcome = prepared_run(tmp_path, degraded=True)
    payloads = post_recorder(monkeypatch, [])
    verdict = "BLOCK" if policy is REQUEST_CHANGES else "PASS"
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict=verdict,
        publish_policy=policy.model_copy(update={"dismiss_on_pass": True}),
        policy_source="repository",
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "degraded"
    assert result.facts.dismissed_review_ids == []


def test_missing_identity_and_failed_reads_clamp_to_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=None,
        github=FakeGitHub([]),
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "login_unknown"
    payloads.clear()
    failing = FakeGitHub([], rest={PR_PATH: RuntimeError("HTTP 500")})
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=failing,
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "read_failed"
    payloads.clear()
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
        policy_verified=False,
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "snapshot_unverified"


def test_no_verdict_is_a_comment_without_a_recorded_clamp_when_policy_agrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict=None,
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "no_verdict"


def test_event_override_only_downgrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
        event_override="comment",
    )
    assert payloads[0]["event"] == "COMMENT"
    assert result.facts is not None and result.facts.event_clamped_reason == "event_override"
    with pytest.raises(EventOverrideRejected, match="exceeds the policy-selected event COMMENT"):
        publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md="",
            merged=merged,
            outcome=outcome,
            execute=True,
            identity=BOT,
            github=github_with([empty_threads()]),
            verdict="BLOCK",
            publish_policy=PublishPolicy(),
            policy_source="repository",
            event_override="request_changes",
        )
    with pytest.raises(EventOverrideRejected):
        publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md="",
            merged=merged,
            outcome=outcome,
            execute=True,
            identity=BOT,
            github=github_with([empty_threads()]),
            verdict="PASS",
            publish_policy=PublishPolicy(),
            policy_source="repository",
            event_override="approve",
        )
    # requesting exactly the selected event is a no-op
    payloads.clear()
    publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github_with([empty_threads()]),
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
        event_override="request_changes",
    )
    assert payloads[0]["event"] == "REQUEST_CHANGES"


def test_second_request_changes_on_the_same_head_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    calls: list[str] = []
    post_recorder(monkeypatch, calls)
    github = github_with(
        [empty_threads()], rest={REVIEWS_PATH: [own_review(7, head=H2, event="REQUEST_CHANGES")]}
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert (
        calls == [] and result.state == "skipped" and result.skipped == "duplicate_review_same_head"
    )
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert (
        summary.publication_skipped == "duplicate_review_same_head"
        and summary.publish.event is None
    )
    # an earlier head's REQUEST_CHANGES, or another author's, does not count
    calls.clear()
    github = github_with(
        [empty_threads()],
        rest={
            REVIEWS_PATH: [
                own_review(7, head=H1, event="REQUEST_CHANGES"),
                own_review(8, head=H2, event="REQUEST_CHANGES", login="alice", kind="User"),
                own_review(9, head=H2, event="REQUEST_CHANGES", marked=False),
            ]
        },
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="BLOCK",
        publish_policy=REQUEST_CHANGES,
        policy_source="repository",
    )
    assert calls == ["POST review"] and result.event == "REQUEST_CHANGES"


def test_same_head_comment_rerun_with_nothing_new_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)
    calls: list[str] = []
    post_recorder(monkeypatch, calls)
    github = github_with(
        [empty_threads()], rest={REVIEWS_PATH: [own_review(7, head=H2, event="COMMENT")]}
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="PASS",
        publish_policy=PublishPolicy(),
        policy_source="repository",
    )
    assert calls == [] and result.skipped == "duplicate_review_same_head"


def test_dismiss_on_pass_touches_exactly_rvws_own_earlier_request_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)
    post_recorder(monkeypatch, [])
    reviews = [
        own_review(11, head=H1, event="REQUEST_CHANGES"),
        own_review(12, head="3" * 40, event="REQUEST_CHANGES"),
        own_review(13, head=H1, event="REQUEST_CHANGES", login="alice", kind="User"),
        own_review(14, head=H1, event="COMMENT"),
        own_review(15, head=H2, event="REQUEST_CHANGES"),  # same head: never dismissed
        own_review(16, head=H1, event="REQUEST_CHANGES", state="DISMISSED"),
    ]
    github = github_with(
        [empty_threads()],
        rest={REVIEWS_PATH: reviews, f"{PR_PATH}/reviews/12": {"state": "DISMISSED"}},
    )
    github.rest_map[f"{PR_PATH}/reviews/12/dismissals"] = PublishError(
        "Validation Failed (HTTP 422)", status_code=422
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="PASS",
        publish_policy=DISMISS,
        policy_source="repository",
    )
    dismissals = [call for call in github.calls if "/dismissals" in call[0]]
    assert [call[0] for call in dismissals] == [
        f"PUT {PR_PATH}/reviews/11/dismissals",
        f"PUT {PR_PATH}/reviews/12/dismissals",
    ]
    assert dismissals[0][1] == {
        "message": "Dismissed: a newer commit passed review.",
        "event": "DISMISS",
    }
    assert result.facts is not None and sorted(result.facts.dismissed_review_ids) == [11, 12]
    assert result.facts.dismiss_failed_review_ids == []
    # a 422 whose review is still not dismissed is recorded as a failure, never as done
    github = github_with(
        [empty_threads()],
        rest={
            REVIEWS_PATH: [own_review(21, head=H1, event="REQUEST_CHANGES")],
            f"{PR_PATH}/reviews/21": {"state": "CHANGES_REQUESTED"},
        },
    )
    github.rest_map[f"{PR_PATH}/reviews/21/dismissals"] = PublishError(
        "Validation Failed (HTTP 422)", status_code=422
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="PASS",
        publish_policy=DISMISS,
        policy_source="repository",
    )
    assert (
        result.facts is not None
        and result.facts.dismissed_review_ids == []
        and result.facts.dismiss_failed_review_ids == [21]
    )


def test_dismissal_requires_pass_policy_and_no_clamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)
    post_recorder(monkeypatch, [])
    reviews: dict[str, object] = {REVIEWS_PATH: [own_review(11, head=H1, event="REQUEST_CHANGES")]}
    for verdict, policy in (("BLOCK", DISMISS), ("PASS", REQUEST_CHANGES)):
        github = github_with([empty_threads()], rest=reviews)
        result = publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md="",
            merged=merged,
            outcome=outcome,
            execute=True,
            identity=BOT,
            github=github,
            verdict=verdict,  # type: ignore[arg-type]
            publish_policy=policy,
            policy_source="repository",
        )
        assert not any("/dismissals" in call[0] for call in github.calls)
        assert result.facts is not None and result.facts.dismissed_review_ids == []


def test_moved_head_skips_every_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    calls: list[str] = []
    post_recorder(monkeypatch, calls)
    github = github_with(
        [empty_threads()],
        rest={
            PR_PATH: {"head": {"sha": "f" * 40}},
            REVIEWS_PATH: [own_review(11, head=H1, event="REQUEST_CHANGES")],
        },
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        identity=BOT,
        github=github,
        verdict="PASS",
        publish_policy=DISMISS,
        policy_source="repository",
    )
    assert calls == [] and writes(github) == ["threads"]
    assert not any("/dismissals" in call[0] for call in github.calls)
    assert result.skipped == "head_moved" and result.state == "skipped"
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publication_skipped == "head_moved"


def test_dry_run_plan_names_the_event_and_dismissals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)

    def forbidden(cmd: list[str], input_json: str) -> str:
        raise AssertionError("dry run wrote a review")

    monkeypatch.setattr(publish_module, "_run", forbidden)
    github = github_with(
        [empty_threads()], rest={REVIEWS_PATH: [own_review(11, head=H1, event="REQUEST_CHANGES")]}
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        identity=BOT,
        github=github,
        verdict="PASS",
        publish_policy=DISMISS,
        policy_source="repository",
        plan_threads=True,
    )
    assert not any("/dismissals" in call[0] for call in github.calls)
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert payload["event"] == "COMMENT" and payload["plan"]["event"] == "COMMENT"
    assert payload["plan"]["dismiss"] == [11] and result.state == "commented"


def test_policy_snapshot_round_trips_through_the_run_store(tmp_path: Path) -> None:
    target = ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha=H2,
        changed_paths=["a.py"],
        diff="",
        pr_number=42,
    )
    run = RunStore(tmp_path).create(target)
    assert run.load_policy() is None
    policy = validate_policy(
        {
            "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
            "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
            "block_when": {"severity_at_least": "blocker"},
            "publish_state": "comment",
            "publish": {"on_block": "request_changes"},
        }
    )
    run.save_policy(EffectivePolicy(policy, "repository", "abc:.rvw/policies/auto.yaml"))
    loaded = run.load_policy()
    assert loaded is not None and loaded.source == "repository" and loaded.policy == policy
    assert loaded.path == "abc:.rvw/policies/auto.yaml"
    (run.dir / "policy.json").write_text(json.dumps({"source": "head", "policy": {}}))
    with pytest.raises(ValueError, match="malformed"):
        run.load_policy()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def repo_with_policy(tmp_path: Path, publish_block: str) -> tuple[Path, ResolvedTarget]:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    git(checkout, "init", "--quiet")
    git(checkout, "config", "user.name", "Fixture")
    git(checkout, "config", "user.email", "fixture@example.invalid")
    policy = checkout / ".rvw" / "policies" / "auto.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "promote_to_blocker:\n  agreement_at_least: 2\n  severity_at_least: warning\n"
        "drop:\n  agreement_at_most: 1\n  severity_at_most: suggestion\n"
        "block_when:\n  severity_at_least: blocker\npublish_state: comment\n" + publish_block,
        encoding="utf-8",
    )
    git(checkout, "add", ".")
    git(checkout, "commit", "--quiet", "-m", "base")
    base = git(checkout, "rev-parse", "HEAD")
    target = ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha=base,
        head_sha=H2,
        changed_paths=["a.py"],
        diff="",
        pr_number=42,
    )
    return checkout, target


def test_publication_policy_prefers_the_base_ref_then_the_api_then_the_unverified_snapshot(
    tmp_path: Path,
) -> None:
    checkout, target = repo_with_policy(tmp_path, "publish:\n  on_block: request_changes\n")
    run = RunStore(tmp_path / "runs").create(target)
    run.save_policy(
        EffectivePolicy(
            validate_policy(
                {
                    "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
                    "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
                    "block_when": {"severity_at_least": "blocker"},
                    "publish_state": "comment",
                    "publish": {"on_pass": "approve", "approve_requires_explicit_opt_in": False},
                }
            ),
            "repository",
            "forged",
        )
    )
    local = cli_module._publication_policy(run, target, cwd=checkout)
    assert (local.policy.publish.on_block, local.source, local.verified) == (
        "request_changes",
        "repository",
        True,
    )
    assert local.policy.publish.on_pass == "comment"  # the forged snapshot was never read
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    import base64

    contents: dict[str, object] = {
        f"repos/owner/repo/contents/.rvw/policies/auto.yaml?ref={target.base_sha}": {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(
                (checkout / ".rvw/policies/auto.yaml").read_bytes()
            ).decode(),
        }
    }
    fetched = cli_module._publication_policy(
        run, target, cwd=elsewhere, client=FakeGitHub([], rest=contents)
    )
    assert (fetched.policy.publish.on_block, fetched.source, fetched.verified) == (
        "request_changes",
        "repository",
        True,
    )
    absent = FakeGitHub(
        [], rest={next(iter(contents)): PublishError("Not Found (HTTP 404)", status_code=404)}
    )
    default = cli_module._publication_policy(run, target, cwd=elsewhere, client=absent)
    assert (default.policy.publish.on_block, default.source, default.verified) == (
        "comment",
        "default",
        True,
    )
    snapshot = cli_module._publication_policy(run, target, cwd=elsewhere)
    assert (snapshot.policy.publish.on_pass, snapshot.source, snapshot.verified) == (
        "approve",
        "repository",
        False,
    )
    fresh = RunStore(tmp_path / "fresh").create(target)
    none = cli_module._publication_policy(fresh, target, cwd=elsewhere)
    assert (none.policy.publish, none.source, none.verified) == (PublishPolicy(), "default", True)
