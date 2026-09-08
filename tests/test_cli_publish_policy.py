"""CLI surfaces follow the publish policy: run passes the verdict, publish downgrades only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cli_phase5 import fixture_artifacts, patch_pipeline, policy_file
from test_publish_events import empty_threads
from test_publish_threads import BOT, FakeGitHub, github_with
from typer.testing import CliRunner

import rvw.cli as cli_module
import rvw.publish as publish_module
from rvw.policy import EffectivePolicy, PublishPolicy, validate_policy
from rvw.presentation import PresentationConfig
from rvw.publish import PublishError, PublishResult

runner = CliRunner()


def forbidden_write(cmd: list[str], input_json: str) -> str:
    raise AssertionError(f"dry run wrote a review: {cmd} {input_json}")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "load_repo_presentation", lambda *_, **__: PresentationConfig())
    monkeypatch.setattr(cli_module, "provision_checkout", lambda **_: Path.cwd())
    monkeypatch.setattr(cli_module, "resolve_own_identity", lambda *_, **__: None)


def test_run_passes_the_verdict_and_policy_so_block_posts_request_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    patch_pipeline(monkeypatch, artifacts)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: artifacts.target)
    calls: list[dict[str, object]] = []

    def fake_publish(**kwargs: object) -> PublishResult:
        calls.append(kwargs)
        return PublishResult(
            review_url="https://example.test/r/1",
            inline_count=0,
            body_fallback_count=0,
            state="changes_requested",
            event="REQUEST_CHANGES",
        )

    monkeypatch.setattr(cli_module, "publish_review", fake_publish)
    policy = policy_file(tmp_path, "comment")
    policy.write_text(
        policy.read_text() + "publish:\n  on_block: request_changes\n  dismiss_on_pass: true\n"
    )
    out = tmp_path / "result"
    result = runner.invoke(
        cli_module.app,
        [
            "run",
            "--target",
            "42",
            "--policy",
            str(policy),
            "--out",
            str(out),
            "--publish",
            "github-review",
            "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    assert len(calls) == 1
    assert calls[0]["verdict"] == "BLOCK"
    publish_policy = calls[0]["publish_policy"]
    assert isinstance(publish_policy, PublishPolicy)
    assert publish_policy.on_block == "request_changes" and publish_policy.dismiss_on_pass is True
    assert calls[0]["policy_source"] == "explicit"
    snapshot = json.loads((out / "policy.json").read_text())
    assert (
        snapshot["source"] == "explicit"
        and snapshot["policy"]["publish"]["on_block"] == "request_changes"
    )


def saved_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    run = artifacts.run
    run.save_target(artifacts.target)
    run.save_merge(artifacts.merged)
    assert artifacts.outcome is not None
    run.save_outcome(artifacts.outcome)
    run.save_discover(artifacts.discovered)
    run.save_presentation(PresentationConfig())
    return artifacts


def test_publish_event_override_is_rejected_when_it_exceeds_the_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = saved_run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        publish_module, "_run", lambda *_: (_ for _ in ()).throw(AssertionError("wrote"))
    )
    monkeypatch.setattr(cli_module, "GhCliClient", lambda: FakeGitHub([]))
    result = runner.invoke(
        cli_module.app,
        [
            "publish",
            "--run",
            artifacts.run.run_id,
            "--out",
            str(tmp_path / "runs"),
            "--event",
            "request_changes",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "event_override_exceeds_policy" in result.stderr
    downgrade = runner.invoke(
        cli_module.app,
        [
            "publish",
            "--run",
            artifacts.run.run_id,
            "--out",
            str(tmp_path / "runs"),
            "--event",
            "comment",
        ],
    )
    assert downgrade.exit_code == 0, downgrade.output
    payload = json.loads((artifacts.run.dir / "publish-payload.json").read_text())
    assert payload["event"] == "COMMENT" and payload["commit_id"] == "b" * 40
    assert "event: COMMENT (policy default" in downgrade.stdout


def test_publish_uses_the_repository_policy_when_the_snapshot_is_the_only_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = saved_run(tmp_path, monkeypatch)
    artifacts.run.save_policy(
        EffectivePolicy(
            validate_policy(
                {
                    "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
                    "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
                    "block_when": {"severity_at_least": "blocker"},
                    "publish_state": "comment",
                    "publish": {"on_block": "request_changes"},
                }
            ),
            "repository",
            "snapshot",
        )
    )
    monkeypatch.setattr(publish_module, "_run", forbidden_write)
    contents = f"repos/owner/repo/contents/.rvw/policies/auto.yaml?ref={'a' * 40}"
    github = github_with(
        [empty_threads()],
        rest={
            contents: PublishError("HTTP 500", status_code=500),
            "repos/owner/repo/pulls/42": {"head": {"sha": "b" * 40}},
        },
    )
    monkeypatch.setattr(cli_module, "GhCliClient", lambda: github)
    monkeypatch.setattr(cli_module, "resolve_own_identity", lambda *_, **__: BOT)
    result = runner.invoke(
        cli_module.app,
        ["publish", "--run", artifacts.run.run_id, "--out", str(tmp_path / "runs")],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((artifacts.run.dir / "publish-payload.json").read_text())
    # the snapshot alone is unverified: a BLOCK with request_changes still clamps to COMMENT
    assert payload["event"] == "COMMENT"
    assert payload["plan"]["event"] == "COMMENT"
    assert "clamped: snapshot_unverified" in result.stdout


def test_publish_and_review_reject_an_invalid_repository_publish_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = saved_run(tmp_path, monkeypatch)
    (artifacts.run.dir / "policy.json").write_text(
        json.dumps(
            {
                "source": "repository",
                "path": "x",
                "policy": {
                    "promote_to_blocker": {"agreement_at_least": 2, "severity_at_least": "warning"},
                    "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
                    "block_when": {"severity_at_least": "blocker"},
                    "publish_state": "comment",
                    "publish": {"on_pass": "approve"},
                },
            }
        )
    )
    monkeypatch.setattr(cli_module, "GhCliClient", lambda: FakeGitHub([]))
    result = runner.invoke(
        cli_module.app, ["publish", "--run", artifacts.run.run_id, "--out", str(tmp_path / "runs")]
    )
    assert result.exit_code == 2, result.output
    assert (
        "publish_policy_invalid: publish_policy_invalid: approve_not_opted_in"
        in result.stderr.replace("\n", "")
    )


def test_publish_mode_alias_is_accepted_with_a_deprecation_warning_and_normalised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=False)
    patch_pipeline(monkeypatch, artifacts)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: artifacts.target)
    calls: list[dict[str, object]] = []

    def fake_publish(**kwargs: object) -> PublishResult:
        calls.append(kwargs)
        return PublishResult(
            review_url="https://example.test/r/1",
            inline_count=0,
            body_fallback_count=0,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "publish_review", fake_publish)
    out = tmp_path / "result"
    result = runner.invoke(
        cli_module.app,
        [
            "run",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path, "comment")),
            "--out",
            str(out),
            "--publish",
            "github-comment",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "github-comment is deprecated" in result.stderr
    process = json.loads((out / "process.json").read_text())
    assert process["runtime"]["publish"] == "github-review"
    assert process["command"][process["command"].index("--publish") + 1] == "github-review"
    assert len(calls) == 1
    canonical = runner.invoke(
        cli_module.app,
        [
            "run",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path, "comment")),
            "--out",
            str(tmp_path / "canonical"),
            "--publish",
            "github-review",
            "--json",
        ],
    )
    assert canonical.exit_code == 0, canonical.output
    assert "deprecated" not in canonical.stderr
