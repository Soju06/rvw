"""Explicit policy values for every Codex runtime invocation."""

from __future__ import annotations

import json
from dataclasses import dataclass

REASONING_SUMMARY_VALUES = frozenset({"auto", "concise", "detailed", "none"})


@dataclass(frozen=True, slots=True)
class CodexRuntimePolicy:
    """Model and reasoning configuration rendered for ``codex exec``."""

    model: str
    reasoning_effort: str
    reasoning_summary: str = "detailed"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.reasoning_effort.strip():
            raise ValueError("reasoning_effort must be non-empty")
        if self.reasoning_summary not in REASONING_SUMMARY_VALUES:
            allowed = ", ".join(sorted(REASONING_SUMMARY_VALUES))
            raise ValueError(f"reasoning_summary must be one of: {allowed}")

    def command_args(self) -> tuple[str, ...]:
        """Return the stable CLI arguments that override ambient configuration."""

        return (
            "--model",
            self.model,
            "-c",
            f"model_reasoning_effort={json.dumps(self.reasoning_effort)}",
            "-c",
            f"model_reasoning_summary={json.dumps(self.reasoning_summary)}",
        )

    def payload(self) -> dict[str, str]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_summary": self.reasoning_summary,
        }


DEFAULT_CODEX_RUNTIME_POLICY = CodexRuntimePolicy(
    model="gpt-5.6-sol",
    reasoning_effort="max",
)


__all__ = ["DEFAULT_CODEX_RUNTIME_POLICY", "REASONING_SUMMARY_VALUES", "CodexRuntimePolicy"]
