from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rvw.cli import app
from rvw.policy import packaged_policy

runner = CliRunner()


def _policy_file(tmp_path: Path, pull_request: dict) -> Path:
    path = tmp_path / "auto.yaml"
    raw = packaged_policy().policy.model_dump(mode="json")
    raw["triggers"]["events"]["pull_request"] = pull_request
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_empty_enabled_actions_warn_without_rejecting_policy(tmp_path: Path) -> None:
    path = _policy_file(tmp_path, {"enabled": True, "actions": []})

    result = runner.invoke(app, ["policy", "lint", str(path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == [
        {
            "reason": "empty-pull-request-actions",
            "path": str(path),
            "severity": "warning",
            "message": "pull_request.enabled is true but actions is empty; automatic reviews "
            "are disabled. Set enabled: false to make this explicit.",
        }
    ]


def test_empty_enabled_actions_warning_is_visible_without_json(tmp_path: Path) -> None:
    path = _policy_file(tmp_path, {"actions": []})

    result = runner.invoke(app, ["policy", "lint", str(path)])

    assert result.exit_code == 0, result.output
    assert "warning: empty-pull-request-actions:" in result.stderr
    assert "automatic reviews are disabled" in " ".join(result.stderr.split())


@pytest.mark.parametrize(
    "pull_request",
    [{"enabled": False, "actions": []}, {"actions": ["opened"]}, {}],
)
def test_intentional_disable_and_selected_actions_do_not_warn(
    tmp_path: Path, pull_request: dict
) -> None:
    path = _policy_file(tmp_path, pull_request)

    result = runner.invoke(app, ["policy", "lint", str(path), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"ok": True, "errors": [], "warnings": []}


def test_policy_lint_defaults_to_repository_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_dir = tmp_path / ".rvw" / "policies"
    policy_dir.mkdir(parents=True)
    _policy_file(policy_dir, {"actions": []})
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["policy", "lint", "--json"])

    assert result.exit_code == 0, result.output
    warning = json.loads(result.stdout)["warnings"][0]
    assert warning["reason"] == "empty-pull-request-actions"
    assert warning["path"] == ".rvw/policies/auto.yaml"


def test_policy_lint_keeps_invalid_boolean_an_error(tmp_path: Path) -> None:
    path = _policy_file(tmp_path, {"enabled": "true", "actions": []})

    result = runner.invoke(app, ["policy", "lint", str(path), "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["warnings"] == []
    assert payload["errors"][0]["reason"] == "invalid_policy"
    assert payload["errors"][0]["severity"] == "error"
    assert "bool_type" in payload["errors"][0]["message"]


def test_policy_lint_keeps_publication_error_classification(tmp_path: Path) -> None:
    path = _policy_file(tmp_path, {})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["publish"]["on_pass"] = "approve"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    result = runner.invoke(app, ["policy", "lint", str(path), "--json"])

    assert result.exit_code == 2, result.output
    error = json.loads(result.stdout)["errors"][0]
    assert error["reason"] == "publish_policy_invalid"
    assert "approve_not_opted_in" in error["message"]


def test_policy_lint_missing_path_is_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["policy", "lint", str(tmp_path / "absent"), "--json"])

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["errors"][0]["reason"] == "policy_not_found"
