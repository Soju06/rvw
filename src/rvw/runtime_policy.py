"""Explicit policy values for every Codex runtime invocation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

REASONING_SUMMARY_VALUES = frozenset({"auto", "concise", "detailed", "none"})
# The named variants of Codex 0.152.0 ``ReasoningEffort`` (codex-rs/protocol/src/openai_models.rs).
# Codex also accepts an arbitrary custom string; rvw does not, so a typo cannot select an
# unknown effort for an experiment cell.
REASONING_EFFORT_VALUES = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"}
)
CODEX_MODEL_ENV = "RVW_CODEX_MODEL"
REASONING_EFFORT_ENV = "RVW_CODEX_REASONING_EFFORT"


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


def _resolve_model(explicit: str | None, environ: Mapping[str, str]) -> str:
    if explicit is not None:
        value = explicit.strip()
        if not value:
            raise ValueError("--model must be a non-empty model identifier")
        return value
    raw = environ.get(CODEX_MODEL_ENV)
    if raw is None:
        return DEFAULT_CODEX_RUNTIME_POLICY.model
    value = raw.strip()
    if not value:
        raise ValueError(f"{CODEX_MODEL_ENV} must be a non-empty model identifier, got {raw!r}")
    return value


def _resolve_effort(explicit: str | None, environ: Mapping[str, str]) -> str:
    allowed = ", ".join(sorted(REASONING_EFFORT_VALUES))
    if explicit is not None:
        value = explicit.strip()
        if value not in REASONING_EFFORT_VALUES:
            raise ValueError(f"--reasoning-effort must be one of: {allowed}; got {explicit!r}")
        return value
    raw = environ.get(REASONING_EFFORT_ENV)
    if raw is None:
        return DEFAULT_CODEX_RUNTIME_POLICY.reasoning_effort
    value = raw.strip()
    if value not in REASONING_EFFORT_VALUES:
        raise ValueError(f"{REASONING_EFFORT_ENV} must be one of: {allowed}; got {raw!r}")
    return value


def resolve_codex_runtime_policy(
    explicit_model: str | None,
    explicit_effort: str | None,
    environ: Mapping[str, str] = os.environ,
) -> CodexRuntimePolicy:
    """Resolve the model and reasoning effort: explicit option, then environment, then default.

    Each field is resolved independently. An explicit value wins and its environment
    variable is not consulted; a present but malformed value fails closed so the caller can
    reject the run before any runtime work. The reasoning summary keeps the packaged default.
    """

    return CodexRuntimePolicy(
        model=_resolve_model(explicit_model, environ),
        reasoning_effort=_resolve_effort(explicit_effort, environ),
        reasoning_summary=DEFAULT_CODEX_RUNTIME_POLICY.reasoning_summary,
    )


__all__ = [
    "CODEX_MODEL_ENV",
    "DEFAULT_CODEX_RUNTIME_POLICY",
    "REASONING_EFFORT_ENV",
    "REASONING_EFFORT_VALUES",
    "REASONING_SUMMARY_VALUES",
    "CodexRuntimePolicy",
    "resolve_codex_runtime_policy",
]
