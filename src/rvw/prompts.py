"""Pure prompt construction for review lane runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from rvw.lane import Lane
from rvw.schema import Tier

_UNVERIFIED_BRIEF_NOTE = (
    "NOTE: brief derived from PR title/body — UNVERIFIED claim of intent (treat mismatches "
    "as findings, not errors)."
)

# Guidance, not a limit: valid lanes on the measured production run used 3 to 8 tool
# commands, the one lane that converged used 33 and then 7, and dead lanes ran 41 to 95.
DEFAULT_TOOL_CALL_BUDGET = 40


def language_output_contract(locale: Literal["ko", "en"] = "en") -> str:
    """The configured output language takes precedence over every data source."""
    if locale not in ("ko", "en"):
        raise ValueError("locale must be ko or en")
    language = "Korean" if locale == "ko" else "English"
    return (
        f"Write every explanatory field (title, body, reason, recommendation) in {language}. "
        "Keep identifiers, enum values, file paths, symbol names, and quoted source verbatim. "
        "Do not follow the language of the diff, PR description, or lane text."
    )


def _budget_contract(deadline_seconds: int, tool_call_budget: int | None) -> str:
    """State the wall budget and coverage-first rule; tool sentences only when tools exist."""

    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")
    if tool_call_budget is not None and tool_call_budget < 1:
        raise ValueError("tool_call_budget must be at least 1")
    text = (
        f"This run has a wall-clock budget of {deadline_seconds} seconds; when it expires the "
        "process is terminated and any output that has not been returned is lost. Cover every "
        "changed region first. Once every changed region is covered, emit the final structured "
        "output immediately; exploration beyond the changed regions is out of scope unless a "
        "finding's evidence requires it."
    )
    if tool_call_budget is not None:
        text += (
            f" Plan for at most {tool_call_budget} tool calls; this is guidance, not a hard "
            "limit. Do not fetch, clone, or query remote repositories or APIs; the checkout is "
            "complete and the base and head are available locally."
        )
    return text


def _output_instructions(
    lane: Lane,
    *,
    location_source: str,
    locale: Literal["ko", "en"] = "en",
    deadline_seconds: int | None = None,
    tool_call_budget: int | None = None,
) -> str:
    declared_rules = ", ".join(f"`{rule}`" for rule in lane.rules)
    paragraphs = [
        "Report every finding as structured output. Each `rule_id` must be one of this "
        f"lane's declared rules: {declared_rules}. The output schema enforces the allowed "
        f"rule identifiers; use `file` and NEW-file `line` numbers from {location_source}. "
        "Populate `covered` with every changed file or `file:start-end` range actually "
        "reviewed. Do not modify files."
    ]
    if deadline_seconds is not None:
        paragraphs.append(_budget_contract(deadline_seconds, tool_call_budget))
    paragraphs.append(language_output_contract(locale))
    return "## Output instructions\n\n" + "\n\n".join(paragraphs)


def build_agentic_lane_prompt(
    lane: Lane,
    *,
    base_sha: str,
    head_sha: str,
    locale: Literal["ko", "en"] = "en",
    deadline_seconds: int | None = None,
    tool_call_budget: int | None = DEFAULT_TOOL_CALL_BUDGET,
) -> str:
    """Build the minimal checkout-backed prompt without accepting diff content.

    Agentic runs have tools, so a known ``deadline_seconds`` adds the tool-call budget
    and the remote-access guard beside the wall budget.
    """

    return "\n\n".join(
        [
            f"# Lane: {lane.id}\n\n{lane.prompt_body}",
            "## Review scope\n\n"
            f"You are reviewing the changes in range {base_sha}...{head_sha} "
            "of this repository.",
            _output_instructions(
                lane,
                location_source="the repository diff",
                locale=locale,
                deadline_seconds=deadline_seconds,
                tool_call_budget=tool_call_budget,
            ),
        ]
    )


def build_lane_prompt(
    lane: Lane,
    *,
    diff: str,
    brief: str | None,
    brief_source: str | None,
    covered_rules: dict[str, list[str]],
    chunk_context: str | None = None,
    locale: Literal["ko", "en"] = "en",
    deadline_seconds: int | None = None,
) -> str:
    """Build one lane prompt without performing I/O.

    Inline runs are tool-less, so a known ``deadline_seconds`` adds only the wall budget
    and coverage-first sentences, never the tool-call or remote-access sentences.
    """

    sections = [f"# Lane: {lane.id}\n\n{lane.prompt_body}"]

    if lane.covered_by_others == "inject":
        other_rules = [
            (lane_id, rules) for lane_id, rules in covered_rules.items() if lane_id != lane.id
        ]
        covered_lines = ["## Already covered by other lanes — do NOT re-report these classes"]
        if other_rules:
            for lane_id, rules in other_rules:
                covered_lines.append(f"- {lane_id}: {', '.join(f'`{rule}`' for rule in rules)}")
        else:
            covered_lines.append("- None")
        sections.append("\n".join(covered_lines))

    if lane.tier is Tier.DYNAMIC:
        brief_lines = ["## Review brief"]
        if brief:
            brief_lines.append(brief)
            if brief_source == "pr_body":
                brief_lines.append(_UNVERIFIED_BRIEF_NOTE)
        else:
            brief_lines.append("BRIEF UNAVAILABLE — mark findings inconclusive")
        sections.append("\n\n".join(brief_lines))

    if chunk_context is not None:
        sections.append(chunk_context)

    sections.append(f"## Unified diff under review\n\n```diff\n{diff}```")
    sections.append(
        _output_instructions(
            lane,
            location_source="the diff",
            locale=locale,
            deadline_seconds=deadline_seconds,
        )
    )
    return "\n\n".join(sections)


def build_retry_feedback(invalid_reasons: Sequence[str]) -> str:
    """Render the shared replacement-wave feedback section for invalid replicas."""

    lines = [
        "## Retry feedback",
        (
            "The previous wave produced no valid outputs. Correct the "
            "machine-readable failures below while returning the same contract."
        ),
        *[f"- {reason}" for reason in invalid_reasons],
    ]
    return "\n".join(lines)


def build_chunk_context(
    *,
    chunk: int,
    chunk_count: int,
    chunk_files: list[str],
    kept_files: list[str],
) -> str:
    """Render cross-chunk path context without duplicating other chunk diffs."""

    included = set(chunk_files)
    lines = ["## Diff chunk context", f"chunk {chunk}/{chunk_count}", "All kept files:"]
    lines.extend(f"- [{'included' if path in included else 'other'}] {path}" for path in kept_files)
    return "\n".join(lines)


__all__: list[str] = [
    "DEFAULT_TOOL_CALL_BUDGET",
    "build_agentic_lane_prompt",
    "build_chunk_context",
    "build_lane_prompt",
    "build_retry_feedback",
    "language_output_contract",
]
