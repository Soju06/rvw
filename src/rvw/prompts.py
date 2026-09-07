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


def _output_instructions(
    lane: Lane, *, location_source: str, locale: Literal["ko", "en"] = "en"
) -> str:
    declared_rules = ", ".join(f"`{rule}`" for rule in lane.rules)
    return (
        "## Output instructions\n\n"
        "Report every finding as structured output. Each `rule_id` must be one of this "
        f"lane's declared rules: {declared_rules}. The output schema enforces the allowed "
        f"rule identifiers; use `file` and NEW-file `line` numbers from {location_source}. "
        "Populate `covered` with every changed file or `file:start-end` range actually "
        "reviewed. Do not modify files.\n\n" + language_output_contract(locale)
    )


def build_agentic_lane_prompt(
    lane: Lane, *, base_sha: str, head_sha: str, locale: Literal["ko", "en"] = "en"
) -> str:
    """Build the minimal checkout-backed prompt without accepting diff content."""

    return "\n\n".join(
        [
            f"# Lane: {lane.id}\n\n{lane.prompt_body}",
            "## Review scope\n\n"
            f"You are reviewing the changes in range {base_sha}...{head_sha} "
            "of this repository.",
            _output_instructions(lane, location_source="the repository diff", locale=locale),
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
) -> str:
    """Build one lane prompt without performing I/O."""

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
    sections.append(_output_instructions(lane, location_source="the diff", locale=locale))
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
    "build_agentic_lane_prompt",
    "build_chunk_context",
    "build_lane_prompt",
    "build_retry_feedback",
    "language_output_contract",
]
