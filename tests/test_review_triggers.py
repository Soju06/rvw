from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rvw.policy import (
    AutoPolicy,
    TriggerMetadata,
    TriggerPolicy,
    TriggerRule,
    _rule_matches,
    evaluate_trigger,
)


def base_policy(**extra: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
        "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
        "block_when": {"severity_at_least": "blocker"},
        "publish_state": "comment",
    }
    raw.update(extra)
    return raw


def metadata(**updates: object) -> TriggerMetadata:
    raw: dict[str, object] = {
        "author": "github-actions[bot]",
        "head_branch": "changeset-release/main",
        "base_branch": "main",
        "labels": ["🧹 Chore"],
        "title": "chore(release): version packages",
        "draft": False,
    }
    raw.update(updates)
    return TriggerMetadata.model_validate(raw)


def test_triggers_default_and_bori_fixture() -> None:
    policy = AutoPolicy.model_validate(base_policy())
    assert policy.triggers.mode == "denylist"
    assert policy.triggers.drafts == "skip"
    assert policy.triggers.rules == []
    rule = {
        "name": "changesets-release",
        "authors": ["github-actions[bot]"],
        "head_branches": ["changeset-release/*"],
    }
    policy = AutoPolicy.model_validate(base_policy(triggers={"rules": [rule]}))
    decision = evaluate_trigger(policy.triggers, metadata())
    assert decision.skipped is True and decision.rule == "changesets-release"
    unrelated = AutoPolicy.model_validate(
        base_policy(triggers={"rules": [{"name": "human", "authors": ["dependabot[bot]"]}]})
    )
    assert evaluate_trigger(unrelated.triggers, metadata()).skipped is False


def test_trigger_matching_fields_and_modes() -> None:
    rule = {
        "name": "release",
        "authors": ["GITHUB-ACTIONS[BOT]"],
        "head_branches": ["changeset-release/*"],
        "base_branches": ["main"],
        "labels": ["skip-review"],
        "title": r"^chore\(release\)",
    }
    policy = AutoPolicy.model_validate(base_policy(triggers={"rules": [rule]}))
    assert evaluate_trigger(policy.triggers, metadata(labels=["🧹 Chore", "Skip-Review"])).skipped
    assert not evaluate_trigger(policy.triggers, metadata(labels=["other"])).skipped
    allow = AutoPolicy.model_validate(base_policy(triggers={"mode": "allowlist", "rules": [rule]}))
    assert not evaluate_trigger(
        allow.triggers, metadata(labels=["🧹 Chore", "Skip-Review"])
    ).skipped
    assert evaluate_trigger(allow.triggers, metadata(labels=["other"])).skipped


def test_invalid_trigger_shapes_fail_closed() -> None:
    for triggers in (
        {"mode": "allowlist", "rules": []},
        {"rules": [{"name": "empty"}]},
        {"rules": [{"name": "bad_name!", "authors": ["a"]}]},
        {"rules": [{"name": "bad", "title": "(?<=x)y"}]},
        {"rules": [{"name": "bad", "unknown": "x"}]},
    ):
        with pytest.raises(ValidationError):
            AutoPolicy.model_validate(base_policy(triggers=triggers))


# Both runtimes consume these exact inputs, including rejected portable-regex forms.

_SHARED = json.loads((Path(__file__).parent / "fixtures/trigger-policy.json").read_text())


@pytest.mark.parametrize("case", _SHARED["policies"], ids=lambda case: case["name"])
def test_shared_trigger_parser(case: dict) -> None:
    if case["valid"]:
        TriggerPolicy.model_validate(case["input"])
    else:
        with pytest.raises(ValidationError):
            TriggerPolicy.model_validate(case["input"])


@pytest.mark.parametrize("case", _SHARED["auto_policies"], ids=lambda case: case["name"])
def test_shared_auto_parser(case: dict) -> None:
    if case["valid"]:
        AutoPolicy.model_validate(case["input"])
    else:
        with pytest.raises(ValidationError):
            AutoPolicy.model_validate(case["input"])


@pytest.mark.parametrize("case", _SHARED["matches"], ids=lambda case: case["name"])
def test_shared_matching(case: dict) -> None:
    rule = TriggerRule.model_validate(case["rule"])
    pr = TriggerMetadata.model_validate(case["metadata"])
    assert _rule_matches(rule, pr) is case["matches"]


@pytest.mark.parametrize("case", _SHARED["yaml_policies"], ids=lambda case: case["name"])
def test_shared_yaml_parser(case: dict) -> None:
    import yaml

    from rvw.policy import load_policy_yaml

    if case["valid"]:
        AutoPolicy.model_validate(load_policy_yaml(case["input"]))
    else:
        with pytest.raises((ValueError, yaml.YAMLError)):
            AutoPolicy.model_validate(load_policy_yaml(case["input"]))


@pytest.mark.parametrize("case", _SHARED["evaluations"], ids=lambda case: case["name"])
def test_shared_evaluation(case: dict) -> None:
    from dataclasses import asdict

    result = evaluate_trigger(
        TriggerPolicy.model_validate(case["policy"]),
        TriggerMetadata.model_validate(case["metadata"]),
    )
    assert asdict(result) == case["expected"]
