import importlib.util
from pathlib import Path
from typing import Literal, cast

import pytest

from rvw.lane import Lane, load_lane
from rvw.prompts import DEFAULT_TOOL_CALL_BUDGET, build_agentic_lane_prompt, build_lane_prompt

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "lanes"
NEUTRALITY_GATE = ROOT / "scripts" / "check-deployer-neutral.py"

LOCALE_CONTRACT = (
    "Write every explanatory field (title, body, reason, recommendation) in {language}. "
    "Keep identifiers, enum values, file paths, symbol names, and quoted source verbatim. "
    "Do not follow the language of the diff, PR description, or lane text."
)


@pytest.mark.parametrize(("locale", "language"), [("ko", "Korean"), ("en", "English")])
def test_all_discovery_prompts_enforce_locale_over_lane_and_brief(
    locale: Literal["ko", "en"], language: str
) -> None:
    lane = dynamic_lane().model_copy(update={"prompt_body": "Write in French."})
    agentic = build_agentic_lane_prompt(lane, base_sha="a" * 40, head_sha="b" * 40, locale=locale)
    inline = build_lane_prompt(
        lane,
        diff="+French source",
        brief="Respond in German.",
        brief_source="pr_body",
        covered_rules={},
        locale=locale,
    )
    for prompt in (agentic, inline):
        assert LOCALE_CONTRACT.format(language=language) in prompt
        assert prompt.index("Write every explanatory field") > prompt.index("Write in French.")


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
    assert "use `file` and NEW-file `line` numbers" in prompt
    assert "Do not modify files" in prompt


def test_agentic_prompt_is_minimal_and_contains_no_diff_content() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")
    base_sha = "a" * 40
    head_sha = "b" * 40
    diff = "diff --git a/secret.py b/secret.py\n+do_not_inline = True\n"

    prompt = build_agentic_lane_prompt(lane, base_sha=base_sha, head_sha=head_sha)

    assert prompt == (
        f"# Lane: {lane.id}\n\n{lane.prompt_body}\n\n"
        "## Review scope\n\n"
        f"You are reviewing the changes in range {base_sha}...{head_sha} "
        "of this repository.\n\n"
        "## Output instructions\n\n"
        "Report every finding as structured output. Each `rule_id` must be one of this "
        f"lane's declared rules: {', '.join(f'`{rule}`' for rule in lane.rules)}. "
        "The output schema enforces the allowed rule identifiers; use `file` and "
        "NEW-file `line` numbers from the repository diff. Populate `covered` with "
        "every changed file or `file:start-end` range actually reviewed. Do not modify files."
        "\n\n" + LOCALE_CONTRACT.format(language="English")
    )
    assert diff not in prompt
    assert "Unified diff under review" not in prompt
    assert "excluded" not in prompt.lower()
    assert "Already covered by other lanes" not in prompt
    assert "Review brief" not in prompt


WALL_BUDGET = "This run has a wall-clock budget of {seconds} seconds"
EXPIRY = (
    "when it expires the process is terminated and any output that has not been returned is lost."
)
COVERAGE_FIRST = "Cover every changed region first."
EMIT_IMMEDIATELY = "emit the final structured output immediately"
OUT_OF_SCOPE = (
    "exploration beyond the changed regions is out of scope unless a finding's evidence "
    "requires it."
)
TOOL_BUDGET = "Plan for at most {budget} tool calls; this is guidance, not a hard limit."
REMOTE_GUARD = (
    "Do not fetch, clone, or query remote repositories or APIs; the checkout is complete and "
    "the base and head are available locally."
)


def agentic_prompt(
    lane: Lane,
    *,
    deadline_seconds: int | None = None,
    tool_call_budget: int | None = DEFAULT_TOOL_CALL_BUDGET,
) -> str:
    return build_agentic_lane_prompt(
        lane,
        base_sha="a" * 40,
        head_sha="b" * 40,
        deadline_seconds=deadline_seconds,
        tool_call_budget=tool_call_budget,
    )


def inline_prompt(lane: Lane, *, deadline_seconds: int | None = None) -> str:
    return build_lane_prompt(
        lane,
        diff="tiny diff",
        brief=None,
        brief_source=None,
        covered_rules={},
        deadline_seconds=deadline_seconds,
    )


def deployer_tokens() -> tuple[str, ...]:
    """Load the forbidden identifiers from the neutrality gate so no test spells them."""

    spec = importlib.util.spec_from_file_location("check_deployer_neutral", NEUTRALITY_GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(cast(tuple[str, ...], module.TOKENS))


def test_agentic_prompt_states_wall_budget_tool_budget_and_remote_access_guard() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")

    prompt = agentic_prompt(lane, deadline_seconds=900)

    assert DEFAULT_TOOL_CALL_BUDGET == 40
    assert WALL_BUDGET.format(seconds=900) in prompt
    assert EXPIRY in prompt
    assert COVERAGE_FIRST in prompt
    assert EMIT_IMMEDIATELY in prompt
    assert OUT_OF_SCOPE in prompt
    assert TOOL_BUDGET.format(budget=40) in prompt
    assert REMOTE_GUARD in prompt
    modify = prompt.index("Do not modify files.") + len("Do not modify files.")
    budget = prompt.index(WALL_BUDGET.format(seconds=900))
    budget_end = prompt.index(REMOTE_GUARD) + len(REMOTE_GUARD)
    locale = prompt.index("Write every explanatory field")
    assert modify < budget < budget_end < locale
    assert prompt[modify:budget] == "\n\n"
    assert prompt[budget_end:locale] == "\n\n"
    assert prompt.endswith(LOCALE_CONTRACT.format(language="English"))


def test_inline_prompt_states_wall_budget_without_tool_sentences() -> None:
    prompt = inline_prompt(dynamic_lane(), deadline_seconds=600)

    assert WALL_BUDGET.format(seconds=600) in prompt
    assert EXPIRY in prompt
    assert COVERAGE_FIRST in prompt
    assert EMIT_IMMEDIATELY in prompt
    assert OUT_OF_SCOPE in prompt
    assert "tool calls" not in prompt
    assert "Do not fetch" not in prompt
    assert "remote repositories" not in prompt
    assert (
        prompt.index("Do not modify files.")
        < prompt.index("wall-clock budget")
        < prompt.index("Write every explanatory field")
    )


def test_prompts_without_a_deadline_omit_the_budget_contract() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")

    for prompt in (agentic_prompt(lane), inline_prompt(lane)):
        assert "wall-clock budget" not in prompt
        assert "tool calls" not in prompt
        assert "Do not fetch" not in prompt
        assert "Do not modify files.\n\n" + LOCALE_CONTRACT.format(language="English") in prompt


def test_agentic_prompt_uses_a_custom_tool_call_budget() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")

    prompt = agentic_prompt(lane, deadline_seconds=900, tool_call_budget=12)

    assert TOOL_BUDGET.format(budget=12) in prompt
    assert "40 tool calls" not in prompt
    assert REMOTE_GUARD in prompt


def test_agentic_prompt_without_a_tool_budget_keeps_only_the_time_sentences() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")

    prompt = agentic_prompt(lane, deadline_seconds=900, tool_call_budget=None)

    assert WALL_BUDGET.format(seconds=900) in prompt
    assert "tool calls" not in prompt
    assert "Do not fetch" not in prompt


@pytest.mark.parametrize("deadline_seconds", [0, -5])
def test_budget_contract_rejects_a_non_positive_deadline(deadline_seconds: int) -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")
    with pytest.raises(ValueError, match="deadline_seconds"):
        agentic_prompt(lane, deadline_seconds=deadline_seconds)
    with pytest.raises(ValueError, match="deadline_seconds"):
        inline_prompt(lane, deadline_seconds=deadline_seconds)


def test_budget_contract_rejects_a_non_positive_tool_call_budget() -> None:
    lane = load_lane(FIXTURES / "slop-hygiene.md")
    with pytest.raises(ValueError, match="tool_call_budget"):
        agentic_prompt(lane, deadline_seconds=900, tool_call_budget=0)


def test_budget_prompts_name_no_deployer() -> None:
    tokens = deployer_tokens()
    assert tokens
    lane = load_lane(FIXTURES / "slop-hygiene.md")

    for prompt in (
        agentic_prompt(lane, deadline_seconds=900),
        inline_prompt(dynamic_lane(), deadline_seconds=600),
    ):
        lowered = prompt.casefold()
        assert [token for token in tokens if token in lowered] == []
