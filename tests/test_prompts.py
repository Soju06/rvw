from pathlib import Path

from rvw.lane import Lane, load_lane
from rvw.prompts import build_lane_prompt

FIXTURES = Path(__file__).parent / "fixtures" / "lanes"


def dynamic_lane() -> Lane:
    return Lane.model_validate(
        {
            "lane": "dynamic/goal-parity",
            "tier": "dynamic",
            "rules": ["dynamic/goal-parity"],
            "prompt_body": "Compare the change with its stated goal.",
        }
    )


def test_base_lane_has_no_review_brief() -> None:
    prompt = build_lane_prompt(
        load_lane(FIXTURES / "slop-hygiene.md"),
        diff="diff --git a/a.py b/a.py\n+answer = 42",
        brief="Ship the feature",
        brief_source="operator",
        covered_rules={},
    )

    assert "# Lane: slop-hygiene" in prompt
    assert "# slop-hygiene" in prompt
    assert "## Review brief" not in prompt


def test_dynamic_lane_includes_operator_brief_without_unverified_marker() -> None:
    prompt = build_lane_prompt(
        dynamic_lane(),
        diff="tiny diff",
        brief="Ship the feature",
        brief_source="operator",
        covered_rules={},
    )

    assert "## Review brief\n\nShip the feature" in prompt
    assert "UNVERIFIED claim of intent" not in prompt


def test_pr_body_brief_has_exact_unverified_marker() -> None:
    prompt = build_lane_prompt(
        dynamic_lane(),
        diff="tiny diff",
        brief="Claimed goal",
        brief_source="pr_body",
        covered_rules={},
    )

    assert (
        "NOTE: brief derived from PR title/body — UNVERIFIED claim of intent (treat "
        "mismatches as findings, not errors)."
    ) in prompt


def test_dynamic_lane_marks_missing_brief_inconclusive() -> None:
    prompt = build_lane_prompt(
        dynamic_lane(),
        diff="tiny diff",
        brief="",
        brief_source=None,
        covered_rules={},
    )

    assert "BRIEF UNAVAILABLE — mark findings inconclusive" in prompt


def test_covered_rules_exclude_the_lane_itself() -> None:
    lane = load_lane(FIXTURES / "unscoped-sweep.md")
    prompt = build_lane_prompt(
        lane,
        diff="tiny diff",
        brief=None,
        brief_source=None,
        covered_rules={
            "unscoped-sweep": ["unscoped/correctness"],
            "slop-hygiene": ["slop/dead-assignment", "slop/duplicate-object-key"],
        },
    )

    covered = prompt.split("## Already covered by other lanes", maxsplit=1)[1].split(
        "## Unified diff under review", maxsplit=1
    )[0]
    assert "slop-hygiene" in covered
    assert "slop/dead-assignment" in covered
    assert "unscoped-sweep" not in covered
    assert "unscoped/correctness" not in covered


def test_diff_is_included_verbatim_in_a_fenced_block() -> None:
    diff = "diff --git a/a.py b/a.py\n@@ -0,0 +1,2 @@\n+one\n+two\n"
    prompt = build_lane_prompt(
        load_lane(FIXTURES / "slop-hygiene.md"),
        diff=diff,
        brief=None,
        brief_source=None,
        covered_rules={},
    )

    assert f"```diff\n{diff}```" in prompt
    assert "## Evidence boundary" in prompt
    assert "Do not use tools or inspect files outside this supplied evidence." in prompt
    assert "use `file` and NEW-file `line` numbers" in prompt
    assert "Do not modify files" in prompt
