"""Publication reconciles rvw's own threads: reuse, resolve after the write, fail safe."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage, RunCoverage
from rvw.merge import MergeResult, merge
from rvw.policy import ThreadPolicy
from rvw.publish import (
    GitHubGraphQLError,
    PublishError,
    publish_review,
    resolve_own_identity,
)
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunHandle, RunStore
from rvw.summary import ExecutionSummary, summarize_run
from rvw.target import ResolvedTarget
from rvw.threads import OwnIdentity, build_marker, fingerprint, strip_markers

H1 = "1" * 40
H2 = "2" * 40
BOT = OwnIdentity("review-bot", "bot")
DIFF = (
    "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
    "@@ -1,4 +1,30 @@\n"
    + "".join(f"+line {n}\n" for n in range(1, 31))
    + "diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n"
    "@@ -1,0 +1,30 @@\n" + "".join(f"+line {n}\n" for n in range(1, 31))
)


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha=H2,
        changed_paths=["src/a.py", "src/b.py"],
        diff=DIFF,
        pr_number=42,
    )


def finding(rule: str, path: str, line: int, *, lane: str = "correctness") -> EnrichedFinding:
    return EnrichedFinding(
        rule_id=rule,
        file=path,
        hunk_id=f"{path}@@{line}",
        line=line,
        severity=Severity.BLOCKER,
        body=f"Body of {rule}",
        anchorable=True,
        lane_id=lane,
        replica=1,
    )


def prepared_run(
    tmp_path: Path, *, degraded: bool = False, empty: bool = False
) -> tuple[RunHandle, MergeResult, AdjudicationOutcome]:
    resolved = target()
    run = RunStore(tmp_path).create(resolved)
    run.save_target(resolved)
    findings = (
        []
        if empty
        else [
            finding("r/same", "src/a.py", 10),
            finding("r/new", "src/a.py", 20),
            finding("r/moved", "src/b.py", 4),
        ]
    )
    merged = merge(findings, lane_tiers={"correctness": Tier.BASE})
    verdicts = {group.key: Verdict.CONFIRMED for group in merged.groups}
    outcome = AdjudicationOutcome(
        verdicts=verdicts,
        reasons={key: "reason confirmed" for key in verdicts},
        evidence={group.key: f"evidence {group.rule_id}" for group in merged.groups},
        replica_votes={key: [Verdict.CONFIRMED] * 3 for key in verdicts},
        unresolved=[],
        coerced_rejections=0,
    )
    coverage = [
        LaneCoverage(
            lane_id="correctness",
            dispatched=1,
            valid=0 if degraded else 1,
            findings=0 if degraded else len(findings),
            runs=[
                RunCoverage(
                    replica=1,
                    chunk=1,
                    valid=not degraded,
                    findings=0 if degraded else len(findings),
                    invalid_reason="exit_nonzero:124" if degraded else None,
                )
            ],
        ),
        LaneCoverage(
            lane_id="hygiene",
            dispatched=1,
            valid=1,
            findings=0,
            runs=[RunCoverage(replica=1, chunk=1, valid=True, findings=0, invalid_reason=None)],
        ),
    ]
    discovered = DiscoverResult(lane_results={}, findings=findings, coverage=coverage)
    run.save_discover(discovered)
    run.save_merge(merged)
    run.save_outcome(outcome)
    run.save_summary(summarize_run(run.run_id, discovered))
    return run, merged, outcome


def group_key(merged: MergeResult, rule: str) -> str:
    return next(group.key for group in merged.groups if group.rule_id == rule)


def marker_body(rule: str, path: str, evidence: str, lane: str = "correctness") -> str:
    return "**Blocker**\n\nold body\n\n" + build_marker(
        fingerprint=fingerprint(rule, path, evidence), rule_id=rule, lane_id=lane
    )


def node(
    thread_id: str,
    body: str,
    *,
    path: str,
    line: int | None,
    original_line: int,
    outdated: bool = False,
    resolved: bool = False,
    commit: str = H1,
    login: str = "review-bot",
    typename: str = "Bot",
) -> dict[str, object]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "subjectType": "LINE",
        "path": path,
        "line": line,
        "originalLine": original_line,
        "comments": {
            "totalCount": 1,
            "nodes": [
                {
                    "body": body,
                    "author": {"login": login, "__typename": typename},
                    "originalCommit": {"oid": commit},
                }
            ],
        },
    }


def threads_page(nodes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": nodes,
                }
            }
        }
    }


class FakeGitHub:
    """Records every call; GraphQL responses are served from a queue, REST from a map."""

    def __init__(self, graphql: list[object], rest: dict[str, object] | None = None) -> None:
        self.graphql_queue = list(graphql)
        self.rest_map = rest or {}
        self.calls: list[tuple[str, object]] = []

    def rest(self, method: str, path: str, payload: object = None) -> object:
        self.calls.append((f"{method} {path}", payload))
        response = self.rest_map.get(path)
        if isinstance(response, Exception):
            raise response
        return response

    def graphql(self, query: str, variables: Mapping[str, object]) -> object:
        kind = (
            "resolve"
            if "resolveReviewThread" in query
            else "reply"
            if "addPullRequestReviewThreadReply" in query
            else "threads"
        )
        self.calls.append((kind, dict(variables)))
        response = self.graphql_queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


RESOLVED = {"resolveReviewThread": {"thread": {"id": "x", "isResolved": True}}}
REPLIED = {"addPullRequestReviewThreadReply": {"comment": {"id": "c"}}}


def comments_of(payload: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", payload.get("comments", []))


def variables_of(call: tuple[str, object]) -> dict[str, object]:
    return cast("dict[str, object]", call[1])


COMPARE = f"repos/owner/repo/compare/{H1}...{H2}"
COMPARE_RESPONSE = {
    "merge_base_commit": {"sha": H1},
    "files": [
        {"filename": "src/a.py", "patch": "@@ -3,1 +3,0 @@\n-gone()"},
        {"filename": "src/b.py", "patch": "@@ -1,0 +1,2 @@\n+x\n+y"},
    ],
}


PR_PATH = "repos/owner/repo/pulls/42"
REVIEWS_PATH = f"{PR_PATH}/reviews?per_page=100&page=1"


def github_with(graphql: list[object], rest: dict[str, object] | None = None) -> FakeGitHub:
    return FakeGitHub(
        graphql,
        rest={
            COMPARE: COMPARE_RESPONSE,
            PR_PATH: {"head": {"sha": H2}},
            REVIEWS_PATH: [],
            **(rest or {}),
        },
    )


def writes(github: FakeGitHub) -> list[str]:
    """GraphQL call kinds in order; REST reads (compare) are not writes."""
    return [call[0] for call in github.calls if not call[0].startswith("GET ")]


def fixture_threads() -> list[dict[str, object]]:
    return [
        # same finding, live -> reused
        node(
            "T-same",
            marker_body("r/same", "src/a.py", "evidence r/same"),
            path="src/a.py",
            line=10,
            original_line=8,
        ),
        # gone finding, region edited -> resolved
        node(
            "T-fixed",
            marker_body("r/fixed", "src/a.py", "gone"),
            path="src/a.py",
            line=None,
            original_line=3,
            outdated=True,
        ),
        # same finding, outdated, continues at line 4 -> superseded
        node(
            "T-old",
            marker_body("r/moved", "src/b.py", "evidence r/moved"),
            path="src/b.py",
            line=None,
            original_line=2,
            outdated=True,
        ),
        # another author's thread with a marker -> ignored
        node(
            "T-other",
            marker_body("r/x", "src/a.py", "x"),
            path="src/a.py",
            line=5,
            original_line=5,
            login="alice",
            typename="User",
        ),
    ]


def post_recorder(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *, status_422_first: bool = False
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []

    def fake_run(cmd: list[str], input_json: str) -> str:
        del cmd
        payloads.append(json.loads(input_json))
        calls.append("POST review")
        if status_422_first and len(payloads) == 1:
            raise PublishError("anchor rejected", status_code=422)
        return json.dumps({"html_url": "https://example.test/review/1"})

    monkeypatch.setattr(publish_module, "_run", fake_run)
    return payloads


def test_without_identity_nothing_is_read_and_every_inline_body_ends_with_a_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    github = FakeGitHub([])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        github=github,
    )
    assert github.calls == []
    assert len(comments_of(payloads[0])) == 3
    for comment in comments_of(payloads[0]):
        body = str(comment["body"])
        assert body.rstrip().endswith("-->") and "<!-- rvw:v1 fp=" in body
        assert strip_markers(body) != body
    body = str(payloads[0]["body"])
    assert "<!-- rvw:v1 fp=" not in body
    assert body.rstrip().endswith(f"<!-- rvw:v1 review head={H2} event=COMMENT -->")
    assert payloads[0]["commit_id"] == H2
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publish.threads_skipped_reason == "login_unknown"
    assert summary.publish.actor is None and summary.publish.event == "COMMENT"
    assert result.facts is not None and result.facts.threads_skipped_reason == "login_unknown"


def test_reconciliation_reuses_resolves_after_the_write_and_supersedes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    calls: list[str] = []
    payloads = post_recorder(monkeypatch, calls)
    github = github_with([threads_page(fixture_threads()), RESOLVED, REPLIED, RESOLVED])
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
        thread_policy=ThreadPolicy(),
    )
    posted = {(c["path"], c["line"]) for c in comments_of(payloads[0])}
    assert posted == {("src/a.py", 20), ("src/b.py", 4)}
    assert "Body of r/same" in str(payloads[0]["body"])  # reused finding stays in the body
    kinds = writes(github)
    assert kinds == ["threads", "resolve", "reply", "resolve"]
    assert calls == ["POST review"]
    # every write follows the successful review POST: the read came first, the POST was
    # recorded, and the mutations are the last three GraphQL calls
    assert variables_of(github.calls[-3]) == {"threadId": "T-fixed"}
    assert variables_of(github.calls[-2])["body"] == "Same finding continues at src/b.py:4"
    assert variables_of(github.calls[-1]) == {"threadId": "T-old"}
    facts = result.facts
    assert facts is not None
    assert facts.resolved_thread_ids == ["T-fixed"]
    assert facts.reused_thread_ids == ["T-same"]
    assert facts.superseded_thread_ids == ["T-old"]
    assert facts.actor == "review-bot[bot]" and facts.threads_skipped_reason is None
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publish == facts
    assert result.inline_count == 2


def test_422_fallback_keeps_outdated_threads_open_and_strips_markers_from_the_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    calls: list[str] = []
    payloads = post_recorder(monkeypatch, calls, status_422_first=True)
    github = github_with([threads_page(fixture_threads()), RESOLVED])
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
    )
    assert len(payloads) == 2 and "comments" not in payloads[1]
    assert "<!-- rvw:v1 fp=" not in str(payloads[1]["body"])
    assert str(payloads[1]["body"]).rstrip().endswith("event=COMMENT -->")
    assert writes(github) == ["threads", "resolve"]  # fixed thread resolved; no reply, no supersede
    assert result.facts is not None
    assert result.facts.resolved_thread_ids == ["T-fixed"]
    assert result.facts.superseded_thread_ids == []
    assert sorted(result.facts.reused_thread_ids) == ["T-old", "T-same"]
    assert result.body_fallback_count == 2


def test_degraded_run_reuses_but_never_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path, degraded=True)
    payloads = post_recorder(monkeypatch, [])
    github = github_with([threads_page(fixture_threads())])
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
    )
    assert writes(github) == ["threads"]
    # the outdated matched thread is reused rather than superseded, so nothing is re-posted
    posted = {(c["path"], c["line"]) for c in comments_of(payloads[0])}
    assert posted == {("src/a.py", 20)}
    assert result.facts is not None
    assert result.facts.resolved_thread_ids == [] and result.facts.superseded_thread_ids == []
    assert sorted(result.facts.reused_thread_ids) == ["T-old", "T-same"]
    assert result.facts.threads_skipped_reason == "degraded"


def test_read_failure_degrades_to_todays_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    github = github_with([RuntimeError("network down")])
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
    )
    assert len(comments_of(payloads[0])) == 3
    assert writes(github) == ["threads"]
    assert result.facts is not None and result.facts.threads_skipped_reason == "read_failed"


def test_dry_run_plans_reads_only_when_asked_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)

    def forbidden(cmd: list[str], input_json: str) -> str:
        raise AssertionError("dry run wrote a review")

    monkeypatch.setattr(publish_module, "_run", forbidden)
    silent = github_with([threads_page(fixture_threads())])
    publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        identity=BOT,
        github=silent,
    )
    assert silent.calls == []
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert "plan" not in payload and len(payload["comments"]) == 3
    planning = github_with([threads_page(fixture_threads())])
    publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        identity=BOT,
        github=planning,
        plan_threads=True,
    )
    assert writes(planning) == ["threads"]
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert payload["plan"]["resolve"] == ["T-fixed"]
    assert payload["plan"]["reuse"] == {group_key(merged, "r/same"): "T-same"}
    assert [item["thread_id"] for item in payload["plan"]["supersede"]] == ["T-old"]
    assert len(payload["comments"]) == 2


def test_forbidden_stops_writes_and_not_found_is_counted_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    post_recorder(monkeypatch, [])
    forbidden = github_with(
        [threads_page(fixture_threads()), GitHubGraphQLError("no", types=["FORBIDDEN"])]
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
        github=forbidden,
    )
    assert writes(forbidden) == ["threads", "resolve"]
    assert result.facts is not None and result.facts.threads_skipped_reason == "forbidden"
    assert result.facts.resolved_thread_ids == [] and result.facts.superseded_thread_ids == []
    missing = github_with(
        [
            threads_page(fixture_threads()),
            GitHubGraphQLError("gone", types=["NOT_FOUND"]),
            REPLIED,
            RESOLVED,
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
        github=missing,
    )
    assert result.facts is not None
    assert result.facts.threads_skipped_missing == [
        "T-fixed"
    ] and result.facts.superseded_thread_ids == ["T-old"]


def test_reuse_disabled_posts_everything_and_touches_no_matched_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    payloads = post_recorder(monkeypatch, [])
    github = github_with([threads_page(fixture_threads()), RESOLVED])
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
        thread_policy=ThreadPolicy(reuse_open_thread=False),
    )
    assert len(comments_of(payloads[0])) == 3
    assert writes(github) == ["threads", "resolve"]
    assert result.facts is not None and result.facts.resolved_thread_ids == ["T-fixed"]
    assert result.facts.reused_thread_ids == [] and result.facts.superseded_thread_ids == []


def test_disabled_thread_policy_reads_no_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    post_recorder(monkeypatch, [])
    github = github_with([])
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
        thread_policy=ThreadPolicy(resolve_on_fix=False, reuse_open_thread=False),
    )
    assert writes(github) == []  # the head and own-review reads still happen; no thread read
    assert result.facts is not None
    assert result.facts.threads_skipped_reason == "disabled_by_policy"


def test_resolve_own_identity_prefers_the_environment_then_the_token_user() -> None:
    assert resolve_own_identity({"RVW_GITHUB_LOGIN": "review-bot[bot]"}) == BOT
    assert resolve_own_identity({"RVW_GITHUB_LOGIN": "octocat"}) == OwnIdentity("octocat", "user")
    github = FakeGitHub([], rest={"user": {"login": "octocat", "type": "User"}})
    assert resolve_own_identity({}, client=github) == OwnIdentity("octocat", "user")
    assert github.calls == [("GET user", None)]
    failing = FakeGitHub([], rest={"user": RuntimeError("HTTP 403")})
    assert resolve_own_identity({}, client=failing) is None
    assert resolve_own_identity({}) is None
