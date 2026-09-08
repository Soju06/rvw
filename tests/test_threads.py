"""Finding identity is line-independent and thread reconciliation fails safe."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

import pytest

from rvw.hunks import Hunk, parse_hunks
from rvw.langgate import check_language, prose_segments
from rvw.threads import (
    Candidate,
    GitHubReadError,
    Marker,
    OwnIdentity,
    ReconciliationContext,
    ReviewMarker,
    ReviewThread,
    build_marker,
    build_review_marker,
    compare_hunks,
    diff_hunks_from_text,
    fingerprint,
    graphql_error_types,
    map_old_line,
    normalize_evidence,
    parse_marker,
    parse_review_marker,
    read_review_threads,
    reconcile_threads,
    resolve_thread,
    strip_markers,
)

EVIDENCE = "src/app.py:12:  value = load(raw)\nsrc/app.py:13:  save(value)."
SHIFTED = "src/app.py:40: value   =  load(raw)\nsrc/app.py:41:\tsave(value)"
H1 = "1" * 40
H2 = "2" * 40
OTHER = "9" * 40
BOT = OwnIdentity("review-bot", "bot")


def test_normalize_drops_line_numbers_whitespace_runs_and_trailing_punctuation() -> None:
    assert normalize_evidence(EVIDENCE) == "value = load(raw)\nsave(value)"
    assert normalize_evidence(SHIFTED) == "value = load(raw)\nsave(value)"
    assert normalize_evidence("12 | if x:\n13 | pass;\n\n") == "if x\npass"
    assert normalize_evidence("L7: return") == "return"
    assert normalize_evidence("   ") == ""


def test_fingerprint_is_stable_under_line_shifts_and_whitespace_but_not_evidence() -> None:
    base = fingerprint("bug/severe-defect", "src/app.py", EVIDENCE)
    assert len(base) == 16 and int(base, 16) >= 0
    assert fingerprint("bug/severe-defect", "src/app.py", SHIFTED) == base
    assert fingerprint("bug/severe-defect", "src/app.py", "value = load(raw)\nsave(value)") == base
    assert fingerprint("bug/severe-defect", "src/app.py", "value = load(raw)\nsave(other)") != base
    assert fingerprint("bug/other", "src/app.py", EVIDENCE) != base
    assert fingerprint("bug/severe-defect", "src/other.py", EVIDENCE) != base


def test_marker_round_trip_takes_the_last_marker_and_rejects_unsafe_identifiers() -> None:
    fp = fingerprint("bug/severe-defect", "src/app.py", EVIDENCE)
    marker = build_marker(
        fingerprint=fp, rule_id="bug/severe-defect", lane_id="dynamic/goal-parity"
    )
    assert marker == f"<!-- rvw:v1 fp={fp} rule=bug/severe-defect lane=dynamic/goal-parity -->"
    spoof = build_marker(fingerprint="f" * 16, rule_id="x/y", lane_id="never")
    body = f"**Blocker · `bug/severe-defect`**\n\n{spoof}\n\nTitle\n\n{marker}"
    assert parse_marker(body) == Marker(fp, "bug/severe-defect", "dynamic/goal-parity")
    assert parse_marker("no marker here") is None
    assert parse_marker("<!-- rvw:v1 fp=short rule=a lane=b -->") is None
    assert parse_marker("<!-- rvw:v0 fp=" + "0" * 16 + " rule=a lane=b -->") is None
    with pytest.raises(ValueError, match="fingerprint"):
        build_marker(fingerprint="xyz", rule_id="a", lane_id="b")
    with pytest.raises(ValueError, match="lane"):
        build_marker(fingerprint=fp, rule_id="a", lane_id="bad lane -->")
    assert strip_markers(body) == "**Blocker · `bug/severe-defect`**\n\n\n\nTitle\n\n"


def test_review_marker_round_trip() -> None:
    marker = build_review_marker(head_sha=H2, event="REQUEST_CHANGES")
    assert marker == f"<!-- rvw:v1 review head={H2} event=REQUEST_CHANGES -->"
    assert parse_review_marker("## Summary\n\nprose\n\n" + marker) == ReviewMarker(
        H2, "REQUEST_CHANGES"
    )
    assert parse_review_marker("plain body") is None
    assert parse_review_marker(None) is None
    with pytest.raises(ValueError, match="SHA"):
        build_review_marker(head_sha="abc", event="COMMENT")
    assert strip_markers("body\n\n" + marker) == "body\n\n"


def test_language_gate_ignores_only_rvw_markers() -> None:
    marker = build_marker(fingerprint="0" * 16, rule_id="bug/severe-defect", lane_id="correctness")
    review = build_review_marker(head_sha=H2, event="COMMENT")
    korean = (
        "검증되지 않은 값이 저장 경로로 전달되어 잘못된 데이터가 저장됩니다.\n\n"
        + marker
        + "\n"
        + review
    )
    english = "An unchecked value reaches storage and invalid data is persisted.\n\n" + marker
    assert check_language(korean, "ko")
    assert check_language(english, "en")
    assert not check_language(korean, "en")
    assert all("rvw:v1" not in segment for segment in prose_segments(korean + english))
    injected = "검증되지 않은 값이 저장 경로로 전달됩니다.\n\n<!-- this English sentence hides inside a comment -->"
    assert not check_language(injected, "ko")


def test_own_identity_matches_graphql_and_rest_spellings() -> None:
    bot = OwnIdentity.parse("review-bot[bot]")
    assert bot == BOT and bot.rest_login == "review-bot[bot]"
    assert bot.matches_author("review-bot", "Bot")
    assert bot.matches_author("review-bot[bot]", None)
    assert not bot.matches_author("review-bot", "User")
    assert not bot.matches_author("other", "Bot")
    assert not bot.matches_author(None, "Bot")
    assert bot.matches_user({"login": "review-bot[bot]", "type": "Bot"})
    assert bot.matches_user({"login": "review-bot", "type": "Bot"})
    assert not bot.matches_user({"login": "review-bot", "type": "User"})
    assert not bot.matches_user("review-bot[bot]")
    user = OwnIdentity.parse("octocat")
    assert user == OwnIdentity("octocat", "user") and user.rest_login == "octocat"
    assert user.matches_author("octocat", "User") and not user.matches_author("octocat", "Bot")
    assert OwnIdentity.parse("") is None and OwnIdentity.parse("[bot]") is None
    assert OwnIdentity.from_user({"login": "app[bot]", "type": "Bot"}) == OwnIdentity("app", "bot")
    assert OwnIdentity.from_user({"login": "octocat", "type": "User"}) == user
    assert OwnIdentity.from_user({"login": "", "type": "User"}) is None


DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
+import os
+import sys
 a = 1
 b = 2
 c = 3
@@ -10,4 +12,3 @@
 keep = 1
-removed = 2
 kept = 3
-gone = 4
+added = 5
"""


def test_map_old_line_follows_insertions_deletions_and_untouched_regions() -> None:
    hunks = diff_hunks_from_text(DIFF, "src/app.py")
    assert (map_old_line(hunks, 1).line, map_old_line(hunks, 1).touched) == (3, True)
    assert map_old_line(hunks, 3).line == 5
    assert (map_old_line(hunks, 7).line, map_old_line(hunks, 7).touched) == (9, False)
    assert map_old_line(hunks, 10).line == 12
    assert map_old_line(hunks, 11).kind == "deleted"
    assert map_old_line(hunks, 12).line == 13
    assert map_old_line(hunks, 13).kind == "deleted"
    assert map_old_line(hunks, 20).line == 21
    assert diff_hunks_from_text(DIFF, "src/other.py") == []
    assert map_old_line([], 42).line == 42 and not map_old_line([], 42).touched


def test_map_old_line_handles_pure_insertion_hunks() -> None:
    hunks = parse_hunks("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -5,0 +6,2 @@\n+x\n+y\n")
    assert map_old_line(hunks, 5).line == 5
    assert map_old_line(hunks, 6).line == 8


def thread(
    thread_id: str,
    *,
    path: str,
    rule: str,
    lane: str,
    fp: str,
    original_line: int | None = 1,
    line: int | None = None,
    author: str = "review-bot",
    author_type: str | None = "Bot",
    resolved: bool = False,
    outdated: bool = False,
    commit: str = H1,
    engaged: bool = False,
    subject: Literal["LINE", "FILE"] | None = "LINE",
) -> ReviewThread:
    return ReviewThread(
        id=thread_id,
        path=path,
        line=line,
        original_line=original_line,
        is_resolved=resolved,
        is_outdated=outdated,
        subject_type=subject,
        author=author,
        author_type=author_type,
        original_commit=commit,
        body="**Blocker**\n\nbody\n\n" + build_marker(fingerprint=fp, rule_id=rule, lane_id=lane),
        human_engaged=engaged,
    )


def candidate(
    key: str,
    *,
    path: str,
    line: int | None,
    rule: str,
    lane: str = "correctness",
    evidence: str = "",
    inline: bool = True,
) -> Candidate:
    return Candidate(
        key=key,
        path=path,
        line=line,
        rule_id=rule,
        lane_id=lane,
        fingerprint=fingerprint(rule, path, evidence),
        inline=inline,
    )


def context(**overrides: object) -> ReconciliationContext:
    values: dict[str, object] = {
        "identity": BOT,
        "head_sha": H2,
        "lane_valid": {"correctness": True, "hygiene": True, "security-exposure": False},
        "changed_paths": frozenset({"a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"}),
        "diff_hunks": lambda *_: [],
    }
    values.update(overrides)
    return ReconciliationContext(**cast("dict[str, Any]", values))


B_DIFF = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1,3 +1,4 @@\n a\n-b\n+b2\n+b3\n c\n"
A_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -4,3 +4,2 @@\n x\n-fixed()\n y\n"


def fixture_diff(commit: str, path: str) -> Sequence[Hunk] | None:
    if commit == OTHER:
        return None
    if path == "b.py":
        return diff_hunks_from_text(B_DIFF, "b.py")
    if path == "a.py":
        return diff_hunks_from_text(A_DIFF, "a.py")
    return []


def test_reconciliation_fixture_yields_exact_sets() -> None:
    fp = fingerprint
    threads = [
        # fixed: outdated because the flagged line was deleted; lane valid -> resolve
        thread(
            "T-fixed",
            path="a.py",
            rule="r/x",
            lane="correctness",
            fp=fp("r/x", "a.py", "fixed"),
            original_line=5,
            outdated=True,
        ),
        # persisting: identical fingerprint, live thread -> reused, not posted inline again
        thread(
            "T-same",
            path="a.py",
            rule="r/y",
            lane="correctness",
            fp=fp("r/y", "a.py", "same"),
            original_line=9,
            line=9,
        ),
        # moved: evidence edited so the fingerprint differs; the old line maps onto the new finding
        thread(
            "T-moved",
            path="b.py",
            rule="r/m",
            lane="hygiene",
            fp=fp("r/m", "b.py", "old evidence"),
            original_line=3,
            outdated=True,
        ),
        # outdated but the same finding continues at a new line -> supersede
        thread(
            "T-outdated",
            path="c.py",
            rule="r/o",
            lane="hygiene",
            fp=fp("r/o", "c.py", "continues"),
            original_line=3,
            outdated=True,
        ),
        # ambiguous: two outdated-but-unmappable threads share rule+path with one finding
        thread(
            "T-amb-1",
            path="d.py",
            rule="r/a",
            lane="correctness",
            fp=fp("r/a", "d.py", "one"),
            original_line=4,
            outdated=True,
            commit=OTHER,
        ),
        thread(
            "T-amb-2",
            path="d.py",
            rule="r/a",
            lane="correctness",
            fp=fp("r/a", "d.py", "two"),
            original_line=8,
            outdated=True,
            commit=OTHER,
        ),
        # resolved by the author already; finding gone -> counted separately, untouched
        thread(
            "T-author",
            path="e.py",
            rule="r/e",
            lane="correctness",
            fp=fp("r/e", "e.py", "gone"),
            original_line=1,
            resolved=True,
            outdated=True,
        ),
        # lane died on H2 -> untouched, counted
        thread(
            "T-dead",
            path="f.py",
            rule="r/f",
            lane="security-exposure",
            fp=fp("r/f", "f.py", "gone"),
            original_line=1,
            outdated=True,
        ),
        # live thread whose region did not change and whose finding was not re-found -> unverified
        thread(
            "T-quiet",
            path="g.py",
            rule="r/q",
            lane="correctness",
            fp=fp("r/q", "g.py", "quiet"),
            original_line=2,
            line=2,
        ),
        # another author with a spoofed marker -> ignored entirely
        thread(
            "T-spoof",
            path="a.py",
            rule="r/z",
            lane="correctness",
            fp=fp("r/z", "a.py", "spoof"),
            original_line=7,
            author="mallory",
            author_type="User",
        ),
        # same slug but a User, not the App -> ignored
        thread(
            "T-impostor",
            path="a.py",
            rule="r/z",
            lane="correctness",
            fp=fp("r/z", "a.py", "spoof"),
            original_line=7,
            author_type="User",
        ),
        # no marker at all -> ignored
        ReviewThread(
            id="T-human",
            path="a.py",
            original_line=1,
            author="review-bot",
            author_type="Bot",
            body="human comment",
        ),
    ]
    candidates = [
        candidate("C-same", path="a.py", line=9, rule="r/y", evidence="same"),
        candidate(
            "C-moved", path="b.py", line=4, rule="r/m", lane="hygiene", evidence="new evidence"
        ),
        candidate(
            "C-continues", path="c.py", line=30, rule="r/o", lane="hygiene", evidence="continues"
        ),
        candidate("C-amb", path="d.py", line=6, rule="r/a", evidence="three"),
        candidate("C-new", path="g.py", line=1, rule="r/g", evidence="brand new"),
        candidate("C-spoof", path="a.py", line=7, rule="r/z", evidence="spoof"),
    ]
    plan = reconcile_threads(threads, candidates, context(diff_hunks=fixture_diff))
    assert plan.resolve == ["T-fixed"]
    # Both outdated threads whose finding continues are superseded: the finding is posted
    # again at its new line and the old thread is resolved with the catalog reply.
    assert sorted(
        (item.model_dump() for item in plan.supersede), key=lambda item: item["thread_id"]
    ) == [
        {"thread_id": "T-moved", "candidate_key": "C-moved", "path": "b.py", "line": 4},
        {"thread_id": "T-outdated", "candidate_key": "C-continues", "path": "c.py", "line": 30},
    ]
    assert plan.reused == {"C-same": "T-same"}
    assert sorted(plan.suppressed_inline) == ["C-amb", "C-same"]
    assert sorted(plan.post_inline) == ["C-continues", "C-moved", "C-new", "C-spoof"]
    assert sorted(plan.ambiguous) == ["T-amb-1", "T-amb-2"]
    assert plan.skipped_lane_invalid == ["T-dead"]
    assert plan.skipped_resolved == ["T-author"]
    assert plan.skipped_unverified == ["T-quiet"]
    assert not any(key in plan.outcomes for key in ("T-spoof", "T-impostor", "T-human"))
    assert plan.outcomes == {
        "T-fixed": "resolved",
        "T-same": "reused",
        "T-moved": "superseded",
        "T-outdated": "superseded",
        "T-amb-1": "ambiguous",
        "T-amb-2": "ambiguous",
        "T-author": "skipped_resolved",
        "T-dead": "skipped_lane_invalid",
        "T-quiet": "skipped_unverified",
    }


def gone(thread_id: str = "T", **overrides: object) -> ReviewThread:
    values: dict[str, object] = {
        "path": "a.py",
        "rule": "r/x",
        "lane": "correctness",
        "fp": "0" * 16,
        "original_line": 5,
        "outdated": True,
    }
    values.update(overrides)
    return thread(thread_id, **cast("dict[str, Any]", values))


def test_fail_safe_rules_each_leave_the_thread_open() -> None:
    cases = {
        "skipped_degraded": (gone(), context(degraded=True)),
        "skipped_same_head": (gone(commit=H2), context()),
        "skipped_human_reply": (gone(engaged=True), context()),
        "skipped_lane_invalid": (gone(lane="project/removed"), context()),
        "skipped_unverified": (gone(outdated=False, line=5), context()),
        "skipped_uncovered": (
            gone(path="z.py"),
            context(excluded_paths=frozenset({"z.py"}), changed_paths=frozenset({"z.py"})),
        ),
        "skipped_policy": (gone(), context(resolve_on_fix=False)),
    }
    for expected, (item, ctx) in cases.items():
        plan = reconcile_threads([item], [], ctx)
        assert plan.outcomes == {"T": expected}, expected
        assert plan.resolve == []


def test_outdated_flag_is_trusted_as_change_evidence_but_a_live_thread_is_not() -> None:
    far_edit = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -40,2 +40,3 @@\n x\n+y\n z\n"
    provider = lambda *_: diff_hunks_from_text(far_edit, "a.py")  # noqa: E731
    outdated = reconcile_threads(
        [gone(original_line=5, outdated=True)], [], context(diff_hunks=provider)
    )
    assert outdated.outcomes == {"T": "resolved"}
    live = reconcile_threads(
        [gone(original_line=5, outdated=False, line=5)], [], context(diff_hunks=provider)
    )
    assert live.outcomes == {"T": "skipped_unverified"}


def test_unavailable_mapping_is_unverified_unless_the_file_left_the_diff() -> None:
    item = gone(commit=OTHER)
    assert reconcile_threads([item], [], context(diff_hunks=lambda *_: None)).outcomes == {
        "T": "skipped_unverified"
    }
    left = reconcile_threads(
        [item], [], context(diff_hunks=lambda *_: None, changed_paths=frozenset({"other.py"}))
    )
    assert left.outcomes == {"T": "resolved"}
    unknown = reconcile_threads([item], [], context(diff_hunks=lambda *_: None, changed_paths=None))
    assert unknown.outcomes == {"T": "skipped_unverified"}


def test_uncovered_hunk_on_the_new_head_blocks_resolution() -> None:
    head_diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -3,4 +3,4 @@\n a\n-b\n+c\n d\n e\n"
    )
    head_hunks = parse_hunks(head_diff)
    item = gone(original_line=5, outdated=True)
    covered = reconcile_threads(
        [item], [], context(head_hunks=head_hunks, diff_hunks=lambda *_: head_hunks)
    )
    assert covered.outcomes == {"T": "resolved"}
    uncovered = reconcile_threads(
        [item],
        [],
        context(
            head_hunks=head_hunks,
            diff_hunks=lambda *_: head_hunks,
            uncovered={"correctness": frozenset({head_hunks[0].hunk_id})},
        ),
    )
    assert uncovered.outcomes == {"T": "skipped_uncovered"}


def test_fingerprint_match_requires_uniqueness_then_falls_back_to_lines() -> None:
    shared = fingerprint("r/x", "a.py", "")
    threads = [
        thread(
            "T1", path="a.py", rule="r/x", lane="correctness", fp=shared, original_line=4, line=4
        ),
        thread(
            "T2", path="a.py", rule="r/x", lane="correctness", fp=shared, original_line=9, line=9
        ),
    ]
    only_one = [candidate("C1", path="a.py", line=4, rule="r/x")]
    plan = reconcile_threads(threads, only_one, context())
    assert plan.reused == {"C1": "T1"}
    assert plan.outcomes["T2"] == "skipped_unverified"  # live and unchanged: never resolved
    both = [
        candidate("C1", path="a.py", line=4, rule="r/x"),
        candidate("C2", path="a.py", line=9, rule="r/x"),
    ]
    assert reconcile_threads(threads, both, context()).reused == {"C1": "T1", "C2": "T2"}


def test_unique_pair_matches_regardless_of_mapping() -> None:
    finding = candidate("C", path="a.py", line=8, rule="r/x", evidence="other")
    live = gone(commit=OTHER, outdated=False, line=5)
    plan = reconcile_threads([live], [finding], context(diff_hunks=lambda *_: None))
    assert plan.reused == {"C": "T"} and plan.post_inline == [] and plan.resolve == []
    outdated = gone(commit=OTHER)
    plan = reconcile_threads([outdated], [finding], context(diff_hunks=lambda *_: None))
    assert plan.reused == {} and plan.resolve == [] and plan.post_inline == ["C"]
    assert [item.thread_id for item in plan.supersede] == ["T"]
    assert plan.outcomes == {"T": "superseded"}


def test_two_threads_claiming_one_finding_are_ambiguous() -> None:
    threads = [
        thread(
            "T1", path="a.py", rule="r/x", lane="correctness", fp="0" * 16, original_line=4, line=4
        ),
        thread(
            "T2", path="a.py", rule="r/x", lane="correctness", fp="1" * 16, original_line=4, line=4
        ),
    ]
    plan = reconcile_threads(threads, [candidate("C", path="a.py", line=4, rule="r/x")], context())
    assert sorted(plan.ambiguous) == ["T1", "T2"]
    assert plan.suppressed_inline == ["C"] and plan.post_inline == [] and plan.resolve == []


def test_same_head_rerun_reuses_open_threads_and_never_resolves() -> None:
    same = thread(
        "T",
        path="a.py",
        rule="r/x",
        lane="correctness",
        fp=fingerprint("r/x", "a.py", "e"),
        original_line=3,
        line=3,
        commit=H2,
    )
    missing = thread(
        "T-missing",
        path="a.py",
        rule="r/w",
        lane="correctness",
        fp="a" * 16,
        original_line=8,
        line=8,
        commit=H2,
    )
    plan = reconcile_threads(
        [same, missing], [candidate("C", path="a.py", line=3, rule="r/x", evidence="e")], context()
    )
    assert plan.reused == {"C": "T"} and plan.post_inline == [] and plan.resolve == []
    assert plan.outcomes["T-missing"] == "skipped_same_head"
    edited = thread(
        "T-edited",
        path="a.py",
        rule="r/w",
        lane="correctness",
        fp="a" * 16,
        original_line=8,
        outdated=True,
        commit=H2,
    )
    assert reconcile_threads([edited], [], context()).outcomes == {"T-edited": "skipped_same_head"}


def test_body_only_candidates_match_by_fingerprint_and_are_never_posted_inline() -> None:
    item = thread(
        "T",
        path="a.py",
        rule="r/x",
        lane="correctness",
        fp=fingerprint("r/x", "a.py", "e"),
        original_line=3,
        line=3,
    )
    body_only = candidate("C", path="a.py", line=None, rule="r/x", evidence="e", inline=False)
    plan = reconcile_threads([item], [body_only], context())
    assert plan.reused == {"C": "T"} and plan.suppressed_inline == [] and plan.post_inline == []
    uncertain_now = candidate(
        "C2", path="a.py", line=3, rule="r/x", evidence="changed", inline=False
    )
    plan = reconcile_threads([item], [uncertain_now], context())
    assert plan.reused == {"C2": "T"} and plan.resolve == []


def test_resolved_thread_with_a_persisting_finding_suppresses_the_inline_repost() -> None:
    item = thread(
        "T",
        path="a.py",
        rule="r/x",
        lane="correctness",
        fp=fingerprint("r/x", "a.py", "e"),
        original_line=3,
        resolved=True,
        line=3,
    )
    plan = reconcile_threads(
        [item], [candidate("C", path="a.py", line=3, rule="r/x", evidence="e")], context()
    )
    assert plan.outcomes == {"T": "skipped_resolved"}
    assert plan.suppressed_inline == ["C"] and plan.post_inline == [] and plan.reused == {}


def test_file_level_threads_only_match_by_fingerprint_or_unique_pair() -> None:
    file_thread = thread(
        "T",
        path="a.py",
        rule="r/x",
        lane="correctness",
        fp="0" * 16,
        original_line=None,
        line=None,
        subject="FILE",
        outdated=True,
    )
    plan = reconcile_threads(
        [file_thread], [candidate("C", path="a.py", line=4, rule="r/x", evidence="x")], context()
    )
    assert plan.outcomes == {"T": "superseded"} and plan.post_inline == ["C"]
    alone = reconcile_threads([file_thread], [], context())
    assert alone.outcomes == {"T": "skipped_unverified"}


def test_policy_switches_disable_reuse_and_resolution_independently() -> None:
    threads = [
        thread(
            "T-same",
            path="a.py",
            rule="r/y",
            lane="correctness",
            fp=fingerprint("r/y", "a.py", "same"),
            original_line=9,
            line=9,
        ),
        gone("T-fixed"),
        thread(
            "T-old",
            path="c.py",
            rule="r/o",
            lane="correctness",
            fp=fingerprint("r/o", "c.py", "c"),
            original_line=3,
            outdated=True,
        ),
    ]
    candidates = [
        candidate("C-same", path="a.py", line=9, rule="r/y", evidence="same"),
        candidate("C-old", path="c.py", line=30, rule="r/o", evidence="c"),
    ]
    no_reuse = reconcile_threads(threads, candidates, context(reuse_open_thread=False))
    assert no_reuse.reused == {} and sorted(no_reuse.post_inline) == ["C-old", "C-same"]
    assert no_reuse.resolve == ["T-fixed"] and no_reuse.supersede == []
    assert "T-same" not in no_reuse.outcomes and "T-old" not in no_reuse.outcomes
    no_resolve = reconcile_threads(threads, candidates, context(resolve_on_fix=False))
    assert no_resolve.resolve == [] and no_resolve.supersede == []
    assert no_resolve.outcomes["T-fixed"] == "skipped_policy"
    # a withheld supersession falls back to reuse: nothing is re-posted inline
    assert no_resolve.reused == {"C-same": "T-same", "C-old": "T-old"}
    assert no_resolve.post_inline == [] and no_resolve.outcomes["T-old"] == "reused"


def test_degraded_context_keeps_reuse_but_drops_every_resolution() -> None:
    threads = [
        thread(
            "T-same",
            path="a.py",
            rule="r/y",
            lane="correctness",
            fp=fingerprint("r/y", "a.py", "same"),
            original_line=9,
            line=9,
        ),
        gone("T-fixed"),
        thread(
            "T-old",
            path="c.py",
            rule="r/o",
            lane="correctness",
            fp=fingerprint("r/o", "c.py", "c"),
            original_line=3,
            outdated=True,
        ),
    ]
    candidates = [
        candidate("C-same", path="a.py", line=9, rule="r/y", evidence="same"),
        candidate("C-old", path="c.py", line=30, rule="r/o", evidence="c"),
    ]
    plan = reconcile_threads(threads, candidates, context(degraded=True))
    assert plan.reused == {"C-same": "T-same", "C-old": "T-old"}
    assert plan.resolve == [] and plan.supersede == []
    assert plan.outcomes["T-fixed"] == "skipped_degraded" and plan.post_inline == []


class FakeGitHub:
    def __init__(
        self, graphql_pages: list[object] | None = None, rest: dict[str, object] | None = None
    ) -> None:
        self.pages = list(graphql_pages or [])
        self.rest_responses = rest or {}
        self.calls: list[tuple[str, object, object]] = []

    def rest(self, method: str, path: str, payload: object = None) -> object:
        self.calls.append((method, path, payload))
        response = self.rest_responses[path]
        if isinstance(response, Exception):
            raise response
        return response

    def graphql(self, query: str, variables: Mapping[str, object]) -> object:
        self.calls.append(("graphql", query, dict(variables)))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def page(nodes: list[dict[str, object]], *, cursor: str | None) -> dict[str, object]:
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
                    "nodes": nodes,
                }
            }
        }
    }


def node(
    thread_id: str,
    body: str,
    *,
    login: str | None = "review-bot",
    typename: str = "Bot",
    replies: Sequence[tuple[str, str]] = (),
    total: int | None = None,
    **overrides: object,
) -> dict[str, object]:
    comments: list[dict[str, object]] = [
        {
            "body": body,
            "author": None if login is None else {"login": login, "__typename": typename},
            "originalCommit": {"oid": H1},
        }
    ]
    comments += [
        {
            "body": "reply",
            "author": {"login": name, "__typename": kind},
            "originalCommit": {"oid": H1},
        }
        for name, kind in replies
    ]
    value: dict[str, object] = {
        "id": thread_id,
        "isResolved": False,
        "isOutdated": False,
        "subjectType": "LINE",
        "path": "a.py",
        "line": 3,
        "originalLine": 3,
        "comments": {
            "totalCount": total if total is not None else len(comments),
            "nodes": comments,
        },
    }
    value.update(overrides)
    return value


def test_read_review_threads_paginates_and_marks_human_engagement() -> None:
    marker = build_marker(fingerprint="0" * 16, rule_id="r/x", lane_id="correctness")
    github = FakeGitHub(
        [
            page(
                [
                    node("T1", "text\n\n" + marker),
                    node("T2", "human comment"),
                    node("T3", marker, replies=[("review-bot", "Bot")]),
                    node("T4", marker, replies=[("alice", "User")]),
                ],
                cursor="c1",
            ),
            page(
                [
                    node(
                        "T5",
                        marker,
                        login=None,
                        isResolved=True,
                        line=None,
                        isOutdated=True,
                        subjectType="FILE",
                    ),
                    node("T6", marker, total=99),
                ],
                cursor=None,
            ),
        ]
    )
    threads = read_review_threads(github, "owner/repo", 42, BOT)
    assert [item.id for item in threads] == ["T1", "T3", "T4", "T5", "T6"]
    by_id = {item.id: item for item in threads}
    assert by_id["T1"].author == "review-bot" and by_id["T1"].author_type == "Bot"
    assert not by_id["T3"].human_engaged and by_id["T4"].human_engaged and by_id["T6"].human_engaged
    assert (
        by_id["T5"].author is None
        and by_id["T5"].is_resolved
        and by_id["T5"].subject_type == "FILE"
    )
    variables = [cast("dict[str, object]", call[2]) for call in github.calls]
    assert [item["cursor"] for item in variables] == [None, "c1"]
    assert variables[0] == {"owner": "owner", "name": "repo", "number": 42, "cursor": None}


def test_read_review_threads_rejects_malformed_or_failing_responses() -> None:
    with pytest.raises(GitHubReadError):
        read_review_threads(FakeGitHub([{"repository": None}]), "owner/repo", 42, BOT)
    with pytest.raises(GitHubReadError, match="owner/name"):
        read_review_threads(FakeGitHub([]), "not-a-repo", 42, BOT)
    with pytest.raises(GitHubReadError, match="read failed"):
        read_review_threads(FakeGitHub([RuntimeError("boom")]), "owner/repo", 42, BOT)
    with pytest.raises(GitHubReadError, match="cursor"):
        read_review_threads(FakeGitHub([page([], cursor="")]), "owner/repo", 42, BOT)


def test_resolve_thread_counts_only_a_confirmed_resolution() -> None:
    confirmed = FakeGitHub([{"resolveReviewThread": {"thread": {"id": "T", "isResolved": True}}}])
    assert resolve_thread(confirmed, "T") is True
    assert "resolutionReason: ADDRESSED" in str(confirmed.calls[0][1])
    assert (
        resolve_thread(
            FakeGitHub([{"resolveReviewThread": {"thread": {"id": "T", "isResolved": False}}}]), "T"
        )
        is False
    )
    assert resolve_thread(FakeGitHub([None]), "T") is False


COMPARE_PATCH = "@@ -1,3 +1,4 @@\n a\n-b\n+b2\n+b3\n c"


def test_compare_hunks_synthesises_headers_and_requires_the_merge_base_to_be_the_original() -> None:
    path = f"repos/owner/repo/compare/{H1}...{H2}"
    ok = FakeGitHub(
        rest={
            path: {
                "merge_base_commit": {"sha": H1},
                "files": [{"filename": "b.py", "patch": COMPARE_PATCH}, {"filename": "big.bin"}],
            }
        }
    )
    hunks = compare_hunks(ok, "owner/repo", H1, H2, "b.py")
    assert hunks is not None and len(hunks) == 1 and hunks[0].file == "b.py"
    assert map_old_line(hunks, 2).kind == "deleted" and map_old_line(hunks, 3).line == 4
    assert compare_hunks(ok, "owner/repo", H1, H2, "untouched.py") is None
    assert compare_hunks(ok, "owner/repo", H1, H2, "big.bin") is None
    renamed = FakeGitHub(
        rest={
            path: {
                "merge_base_commit": {"sha": H1},
                "files": [
                    {"filename": "new.py", "previous_filename": "old.py", "patch": COMPARE_PATCH}
                ],
            }
        }
    )
    moved = compare_hunks(renamed, "owner/repo", H1, H2, "old.py")
    assert moved is not None and moved[0].file == "new.py"
    rebased = FakeGitHub(rest={path: {"merge_base_commit": {"sha": OTHER}, "files": []}})
    assert compare_hunks(rebased, "owner/repo", H1, H2, "b.py") is None
    failing = FakeGitHub(rest={path: RuntimeError("HTTP 404")})
    assert compare_hunks(failing, "owner/repo", H1, H2, "b.py") is None


def test_graphql_error_types_are_extracted_from_the_response_body() -> None:
    body = '{"data": null, "errors": [{"type": "FORBIDDEN", "message": "no"}, {"message": "typeless"}]}'
    assert graphql_error_types(body) == ["FORBIDDEN"]
    assert graphql_error_types("not json") == [] and graphql_error_types("[]") == []


def test_compare_absent_path_is_unavailable_not_unchanged() -> None:
    path = f"repos/owner/repo/compare/{H1}...{H2}"
    many = FakeGitHub(
        rest={
            path: {
                "merge_base_commit": {"sha": H1},
                "files": [
                    {"filename": f"other{n}.py", "patch": "@@ -1 +1 @@\n-a\n+b"} for n in range(300)
                ],
            }
        }
    )
    assert compare_hunks(many, "owner/repo", H1, H2, "src/z.py") is None


def test_renamed_file_is_not_treated_as_having_left_the_diff() -> None:
    from rvw.threads import renamed_paths

    head_diff = (
        "diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n"
    )
    assert renamed_paths(head_diff) == frozenset({"old.py"})
    item = gone(path="old.py", commit=OTHER)
    plan = reconcile_threads(
        [item],
        [],
        context(
            changed_paths=frozenset({"new.py"}),
            renamed_from=renamed_paths(head_diff),
            diff_hunks=lambda *_: None,
        ),
    )
    assert plan.outcomes == {"T": "skipped_unverified"}


def test_withheld_supersession_falls_back_to_reuse_and_suppresses_the_repost() -> None:
    old = thread(
        "T-old",
        path="c.py",
        rule="r/o",
        lane="correctness",
        fp=fingerprint("r/o", "c.py", "c"),
        original_line=3,
        outdated=True,
    )
    finding = candidate("C-old", path="c.py", line=30, rule="r/o", evidence="c")
    for ctx in (context(degraded=True), context(resolve_on_fix=False)):
        plan = reconcile_threads([old], [finding], ctx)
        assert plan.reused == {"C-old": "T-old"} and plan.supersede == [] and plan.post_inline == []
        assert plan.outcomes["T-old"] == "reused"
    engaged = thread(
        "T-old",
        path="c.py",
        rule="r/o",
        lane="correctness",
        fp=fingerprint("r/o", "c.py", "c"),
        original_line=3,
        outdated=True,
        engaged=True,
    )
    plan = reconcile_threads([engaged], [finding], context())
    assert plan.reused == {"C-old": "T-old"} and plan.post_inline == []


def test_resolved_predecessor_does_not_disable_the_fingerprint_fast_path() -> None:
    fp = fingerprint("r/x", "a.py", "e")
    threads = [
        thread(
            "T-old",
            path="a.py",
            rule="r/x",
            lane="correctness",
            fp=fp,
            original_line=3,
            resolved=True,
        ),
        thread(
            "T-new", path="a.py", rule="r/x", lane="correctness", fp=fp, original_line=20, line=20
        ),
        thread(
            "T-other",
            path="a.py",
            rule="r/x",
            lane="correctness",
            fp="9" * 16,
            original_line=40,
            line=40,
        ),
    ]
    plan = reconcile_threads(
        threads, [candidate("C", path="a.py", line=20, rule="r/x", evidence="e")], context()
    )
    assert plan.reused == {"C": "T-new"}
    assert "T-old" not in plan.outcomes or plan.outcomes["T-old"] == "skipped_resolved"
    assert plan.outcomes["T-other"] == "skipped_unverified"
