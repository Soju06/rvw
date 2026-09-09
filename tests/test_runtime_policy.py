"""Resolver contract for the per-run Codex model and reasoning-effort override."""

from __future__ import annotations

import pytest

from rvw.runtime_policy import (
    CODEX_MODEL_ENV,
    DEFAULT_CODEX_RUNTIME_POLICY,
    REASONING_EFFORT_ENV,
    REASONING_EFFORT_VALUES,
    CodexRuntimePolicy,
    resolve_codex_runtime_policy,
)

# Codex 0.152.0 ``ReasoningEffort`` named variants, lowercase wire strings.
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent")


def test_packaged_default_policy_is_high_effort() -> None:
    assert (
        CodexRuntimePolicy(
            model="gpt-6-astra", reasoning_effort="high", reasoning_summary="detailed"
        )
        == DEFAULT_CODEX_RUNTIME_POLICY
    )


def test_environment_variable_names_and_effort_enum() -> None:
    assert CODEX_MODEL_ENV == "RVW_CODEX_MODEL"
    assert REASONING_EFFORT_ENV == "RVW_CODEX_REASONING_EFFORT"
    assert isinstance(REASONING_EFFORT_VALUES, frozenset)
    assert frozenset(EFFORTS) == REASONING_EFFORT_VALUES


def test_resolver_returns_the_packaged_default_without_overrides() -> None:
    assert resolve_codex_runtime_policy(None, None, {}) == DEFAULT_CODEX_RUNTIME_POLICY


def test_explicit_values_beat_environment_values() -> None:
    environ = {CODEX_MODEL_ENV: "env-model", REASONING_EFFORT_ENV: "low"}

    policy = resolve_codex_runtime_policy("gpt-5.6-sol", "high", environ)

    assert policy == CodexRuntimePolicy(model="gpt-5.6-sol", reasoning_effort="high")


def test_environment_values_beat_the_packaged_default() -> None:
    environ = {CODEX_MODEL_ENV: "env-model", REASONING_EFFORT_ENV: "low"}

    policy = resolve_codex_runtime_policy(None, None, environ)

    assert policy == CodexRuntimePolicy(model="env-model", reasoning_effort="low")


def test_explicit_model_combines_with_environment_effort() -> None:
    policy = resolve_codex_runtime_policy("gpt-5.6-sol", None, {REASONING_EFFORT_ENV: "medium"})

    assert policy.model == "gpt-5.6-sol"
    assert policy.reasoning_effort == "medium"


def test_environment_model_combines_with_explicit_effort() -> None:
    policy = resolve_codex_runtime_policy(None, "xhigh", {CODEX_MODEL_ENV: "env-model"})

    assert policy.model == "env-model"
    assert policy.reasoning_effort == "xhigh"


def test_each_field_falls_back_to_its_own_default() -> None:
    assert resolve_codex_runtime_policy("gpt-5.6-sol", None, {}).reasoning_effort == "high"
    assert resolve_codex_runtime_policy(None, "medium", {}).model == "gpt-6-astra"
    assert resolve_codex_runtime_policy(None, None, {CODEX_MODEL_ENV: "env-model"}) == (
        CodexRuntimePolicy(model="env-model", reasoning_effort="high")
    )
    assert resolve_codex_runtime_policy(None, None, {REASONING_EFFORT_ENV: "medium"}) == (
        CodexRuntimePolicy(model="gpt-6-astra", reasoning_effort="medium")
    )


def test_resolved_policy_keeps_the_detailed_reasoning_summary() -> None:
    resolved = [
        resolve_codex_runtime_policy(None, None, {}),
        resolve_codex_runtime_policy("gpt-5.6-sol", "high", {}),
        resolve_codex_runtime_policy(
            None, None, {CODEX_MODEL_ENV: "env-model", REASONING_EFFORT_ENV: "low"}
        ),
    ]

    assert {policy.reasoning_summary for policy in resolved} == {"detailed"}


@pytest.mark.parametrize("effort", EFFORTS)
def test_every_named_effort_is_accepted_from_the_environment(effort: str) -> None:
    policy = resolve_codex_runtime_policy(None, None, {REASONING_EFFORT_ENV: effort})

    assert policy.reasoning_effort == effort


@pytest.mark.parametrize("effort", EFFORTS)
def test_every_named_effort_is_accepted_explicitly(effort: str) -> None:
    policy = resolve_codex_runtime_policy(None, effort, {})

    assert policy.reasoning_effort == effort


@pytest.mark.parametrize("value", ["turbo", "Medium", "MAX", "", "   ", "custom:high"])
def test_malformed_environment_effort_names_the_variable_and_lists_values(value: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_codex_runtime_policy(None, None, {REASONING_EFFORT_ENV: value})

    message = str(excinfo.value)
    assert REASONING_EFFORT_ENV in message
    for effort in EFFORTS:
        assert effort in message


@pytest.mark.parametrize("value", ["turbo", "Medium", "MAX", "", "   "])
def test_malformed_explicit_effort_names_the_option_and_lists_values(value: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_codex_runtime_policy(None, value, {})

    message = str(excinfo.value)
    assert "--reasoning-effort" in message
    assert REASONING_EFFORT_ENV not in message
    for effort in EFFORTS:
        assert effort in message


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_environment_model_names_the_variable(value: str) -> None:
    with pytest.raises(ValueError, match=CODEX_MODEL_ENV):
        resolve_codex_runtime_policy(None, None, {CODEX_MODEL_ENV: value})


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_explicit_model_names_the_option(value: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_codex_runtime_policy(value, None, {})

    assert "--model" in str(excinfo.value)
    assert CODEX_MODEL_ENV not in str(excinfo.value)


def test_model_values_are_trimmed() -> None:
    assert resolve_codex_runtime_policy("  gpt-5.6-sol  ", None, {}).model == "gpt-5.6-sol"
    assert (
        resolve_codex_runtime_policy(None, None, {CODEX_MODEL_ENV: " env-model\n"}).model
        == "env-model"
    )


def test_effort_values_are_trimmed_but_not_case_folded() -> None:
    assert resolve_codex_runtime_policy(None, " medium ", {}).reasoning_effort == "medium"
    assert (
        resolve_codex_runtime_policy(None, None, {REASONING_EFFORT_ENV: "high\n"}).reasoning_effort
        == "high"
    )
    with pytest.raises(ValueError, match="--reasoning-effort"):
        resolve_codex_runtime_policy(None, "High", {})


def test_explicit_value_wins_even_when_the_environment_is_malformed() -> None:
    environ = {CODEX_MODEL_ENV: "   ", REASONING_EFFORT_ENV: "turbo"}

    policy = resolve_codex_runtime_policy("gpt-5.6-sol", "high", environ)

    assert policy == CodexRuntimePolicy(model="gpt-5.6-sol", reasoning_effort="high")


def test_explicit_field_does_not_shield_the_other_malformed_environment_field() -> None:
    with pytest.raises(ValueError, match=REASONING_EFFORT_ENV):
        resolve_codex_runtime_policy("gpt-5.6-sol", None, {REASONING_EFFORT_ENV: "turbo"})
    with pytest.raises(ValueError, match=CODEX_MODEL_ENV):
        resolve_codex_runtime_policy(None, "high", {CODEX_MODEL_ENV: " "})


def test_resolver_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CODEX_MODEL_ENV, "env-model")
    monkeypatch.setenv(REASONING_EFFORT_ENV, "medium")

    assert resolve_codex_runtime_policy(None, None) == CodexRuntimePolicy(
        model="env-model", reasoning_effort="medium"
    )

    monkeypatch.delenv(CODEX_MODEL_ENV)
    monkeypatch.delenv(REASONING_EFFORT_ENV)

    assert resolve_codex_runtime_policy(None, None) == DEFAULT_CODEX_RUNTIME_POLICY


def test_value_object_still_accepts_any_non_empty_effort() -> None:
    """Validation lives at the resolver boundary; the dataclass stays a plain value object."""

    assert CodexRuntimePolicy(model="gpt-test", reasoning_effort="custom").reasoning_effort == (
        "custom"
    )
    with pytest.raises(ValueError, match="reasoning_effort"):
        CodexRuntimePolicy(model="gpt-test", reasoning_effort="  ")
