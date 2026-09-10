"""The review event and thread behaviour are repository policy read at the base ref."""

from __future__ import annotations

import json
import subprocess
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_policy import policy, policy_repo

import rvw.policy as policy_module
from rvw.policy import (
    AutoPolicy,
    PublishPolicy,
    PublishPolicyInvalid,
    ThreadPolicy,
    load_policy,
    publish_policy_source,
    validate_policy,
)


def strict_policy(**overrides: object) -> AutoPolicy:
    """Build a policy through the loader boundary that maps publication faults."""
    raw: dict[str, object] = {
        "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
        "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
        "block_when": {"severity_at_least": "blocker"},
        "publish_state": "comment",
    }
    raw.update(overrides)
    return validate_policy(raw)


LEGACY = """promote_to_blocker:
  agreement_at_least: 2
  severity_at_least: warning
drop:
  agreement_at_most: 1
  severity_at_most: suggestion
block_when:
  severity_at_least: blocker
publish_state: comment
"""


def test_publish_and_thread_blocks_default_to_todays_behaviour() -> None:
    loaded = policy()
    assert loaded.publish == PublishPolicy()
    assert loaded.threads == ThreadPolicy()
    assert loaded.publish.model_dump() == {
        "channels": ["checks", "review"],
        "checks": {"on_block": "failure", "on_pass": "success"},
        "inline": {"severity_at_least": "suggestion", "max_comments": None},
        "on_block": "comment",
        "on_pass": "comment",
        "dismiss_on_pass": False,
        "approve_requires_explicit_opt_in": True,
    }
    assert loaded.threads.model_dump() == {"resolve_on_fix": True, "reuse_open_thread": True}


@pytest.mark.parametrize("on_block", ["comment", "request_changes"])
@pytest.mark.parametrize("on_pass", ["comment", "approve", "none"])
@pytest.mark.parametrize("dismiss_on_pass", [False, True])
@pytest.mark.parametrize("resolve_on_fix", [False, True])
@pytest.mark.parametrize("reuse_open_thread", [False, True])
def test_every_valid_combination_loads(
    on_block: str,
    on_pass: str,
    dismiss_on_pass: bool,
    resolve_on_fix: bool,
    reuse_open_thread: bool,
) -> None:
    loaded = policy(
        publish={
            "on_block": on_block,
            "on_pass": on_pass,
            "dismiss_on_pass": dismiss_on_pass,
            "approve_requires_explicit_opt_in": on_pass != "approve",
        },
        threads={"resolve_on_fix": resolve_on_fix, "reuse_open_thread": reuse_open_thread},
    )
    assert loaded.publish.on_block == on_block
    assert loaded.publish.on_pass == on_pass
    assert loaded.publish.dismiss_on_pass is dismiss_on_pass
    assert loaded.threads.resolve_on_fix is resolve_on_fix
    assert loaded.threads.reuse_open_thread is reuse_open_thread


def test_approve_requires_the_explicit_opt_in_in_the_same_file() -> None:
    with pytest.raises(PublishPolicyInvalid, match="approve_not_opted_in") as raised:
        strict_policy(publish={"on_pass": "approve"})
    assert raised.value.reason == "publish_policy_invalid"
    assert raised.value.detail == "approve_not_opted_in"
    assert str(raised.value) == "publish_policy_invalid: approve_not_opted_in"
    opted = strict_policy(publish={"on_pass": "approve", "approve_requires_explicit_opt_in": False})
    assert opted.publish.on_pass == "approve"


@pytest.mark.parametrize(
    "raw",
    [
        {"publish": {"on_block": "approve"}},
        {"publish": {"on_block": "request-changes"}},
        {"publish": {"on_pass": "request_changes"}},
        {"publish": {"dismiss_on_pass": "yes"}},
        {"publish": {"unknown": True}},
        {"publish": "comment"},
        {"threads": {"resolve_on_fix": "true"}},
        {"threads": {"reuse": True}},
    ],
)
def test_unknown_values_fail_closed_with_publish_policy_invalid(raw: dict[str, object]) -> None:
    with pytest.raises(PublishPolicyInvalid) as raised:
        strict_policy(**raw)
    assert raised.value.reason == "publish_policy_invalid"
    assert str(raised.value).startswith("publish_policy_invalid: ")
    assert next(iter(raw)) in str(raised.value)


def test_errors_outside_the_publish_blocks_stay_ordinary_validation_errors() -> None:
    with pytest.raises(ValidationError) as raised:
        validate_policy({"promote_to_blocker": {"agreement_at_least": 0}})
    assert not isinstance(raised.value, PublishPolicyInvalid)


def test_explicit_file_loads_publish_and_thread_blocks(tmp_path: Path) -> None:
    path = tmp_path / "auto.yaml"
    path.write_text(
        LEGACY
        + """publish:
  on_block: request_changes
  on_pass: none
  dismiss_on_pass: true
threads:
  resolve_on_fix: false
""",
        encoding="utf-8",
    )
    loaded = load_policy(path)
    assert loaded.publish.on_block == "request_changes"
    assert loaded.publish.on_pass == "none"
    assert loaded.publish.dismiss_on_pass is True
    assert loaded.publish.approve_requires_explicit_opt_in is True
    assert loaded.threads.resolve_on_fix is False
    assert loaded.threads.reuse_open_thread is True


def test_missing_repository_policy_selects_defaults(tmp_path: Path) -> None:
    target = policy_repo(tmp_path)
    selected = policy_module.resolve_auto_policy(
        target, cwd=tmp_path, external_path=tmp_path / "missing-external.yaml"
    )
    assert selected.source == "package"
    assert selected.policy.publish == PublishPolicy()
    assert selected.policy.threads == ThreadPolicy()
    assert publish_policy_source(selected.source) == "default"


def test_repository_policy_is_read_from_the_base_ref_not_the_head(tmp_path: Path) -> None:
    base_policy = LEGACY + "publish:\n  on_block: request_changes\n  dismiss_on_pass: true\n"
    target = policy_repo(tmp_path, repository_policy=base_policy)
    # The PR head (working tree) tries to weaken and then break the policy; neither is read.
    head_policy = tmp_path / ".rvw" / "policies" / "auto.yaml"
    head_policy.write_text(LEGACY + "publish:\n  on_pass: approve\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "head"], cwd=tmp_path, check=True)
    with warnings.catch_warnings(record=True) as captured:
        selected = policy_module.resolve_auto_policy(
            target, cwd=tmp_path, external_path=tmp_path / "missing-external.yaml"
        )
    assert captured == []
    assert selected.source == "repository"
    assert selected.policy.publish.on_block == "request_changes"
    assert selected.policy.publish.dismiss_on_pass is True
    assert selected.policy.publish.on_pass == "comment"
    assert publish_policy_source(selected.source) == "repository"


def test_invalid_repository_publish_block_does_not_fall_back(tmp_path: Path) -> None:
    target = policy_repo(tmp_path, repository_policy=LEGACY + "publish:\n  on_pass: approve\n")
    with pytest.raises(PublishPolicyInvalid, match="approve_not_opted_in"):
        policy_module.resolve_auto_policy(
            target, cwd=tmp_path, external_path=tmp_path / "missing-external.yaml"
        )


def test_explicit_policy_source_is_recorded_as_explicit() -> None:
    assert publish_policy_source("explicit") == "explicit"
    assert publish_policy_source("external") == "default"
    assert publish_policy_source("package") == "default"


def test_packaged_default_policy_spells_out_the_publish_and_thread_blocks() -> None:
    from importlib.resources import files

    import yaml

    raw = yaml.safe_load(
        files("rvw").joinpath("resources/policies/auto-default.yaml").read_text(encoding="utf-8")
    )
    assert raw["publish"] == {
        "channels": ["checks", "review"],
        "checks": {"on_block": "failure", "on_pass": "success"},
        "inline": {"severity_at_least": "suggestion", "max_comments": None},
        "on_block": "comment",
        "on_pass": "comment",
        "dismiss_on_pass": False,
        "approve_requires_explicit_opt_in": True,
    }
    assert raw["threads"] == {"resolve_on_fix": True, "reuse_open_thread": True}
    assert AutoPolicy.model_validate(raw).publish == PublishPolicy()


def test_run_rejects_an_invalid_publish_block_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import rvw.cli as cli
    from rvw.presentation import PresentationConfig
    from rvw.target import ResolvedTarget

    resolved = ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["a.py"],
        diff="diff --git a/a.py b/a.py\n",
        pr_number=42,
    )
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: resolved)
    monkeypatch.setattr(cli, "load_repo_presentation", lambda *_, **__: PresentationConfig())
    monkeypatch.setattr(cli, "provision_checkout", lambda **_: Path.cwd())

    async def forbidden(**kwargs: object) -> None:
        raise AssertionError("review must not start with an invalid publish policy")

    monkeypatch.setattr(cli, "_execute_pipeline", forbidden)
    selected = tmp_path / "auto.yaml"
    selected.write_text(LEGACY + "publish:\n  on_pass: approve\n", encoding="utf-8")
    out = tmp_path / "result"
    result = CliRunner().invoke(
        cli.app, ["run", "--target", "42", "--policy", str(selected), "--out", str(out), "--json"]
    )
    assert result.exit_code == 2, result.output
    process = json.loads((out / "process.json").read_text(encoding="utf-8"))
    assert process["status"] == "invalid"
    assert process["failure"]["code"] == "publish_policy_invalid"
    assert "approve_not_opted_in" in process["failure"]["detail"]
