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
from rvw.summary import PublishFacts

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


def test_publish_result_and_thread_summary_use_persisted_presentation_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = saved_run(tmp_path, monkeypatch)
    artifacts.run.save_presentation(PresentationConfig(locale="ko"))
    monkeypatch.setattr(cli_module, "GhCliClient", lambda: FakeGitHub([]))
    monkeypatch.setattr(
        cli_module,
        "publish_review",
        lambda **_kwargs: PublishResult(
            review_url=None,
            inline_count=0,
            body_fallback_count=0,
            state="commented",
            event="COMMENT",
            facts=PublishFacts(
                event="COMMENT",
                policy_source="default",
                reused_thread_ids=["T-reused"],
                resolved_thread_ids=["T-resolved"],
                superseded_thread_ids=["T-superseded"],
                threads_ambiguous=["T-ambiguous"],
                threads_skipped_reason="degraded",
                dismissed_review_ids=[17],
            ),
        ),
    )

    result = runner.invoke(
        cli_module.app,
        ["publish", "--run", artifacts.run.run_id, "--out", str(tmp_path / "runs")],
    )

    assert result.exit_code == 0, result.output
    assert "이벤트: COMMENT (정책 default)" in result.stdout
    assert "스레드: 재사용 1, 해결 1, 교체 1, 모호 1" in result.stdout
    assert "degraded" in result.stdout
    assert "event:" not in result.stdout
    assert "threads:" not in result.stdout


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
    assert "publish_policy_invalid: approve_not_opted_in" in result.stderr.replace("\n", "")


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


def test_run_ignores_the_deprecated_external_publish_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_policy import policy_repo

    from rvw.policy import PublishPolicy, ThreadPolicy

    target = policy_repo(tmp_path / "repo")
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    artifacts.target.base_sha = target.base_sha
    patch_pipeline(monkeypatch, artifacts)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: artifacts.target)
    external = tmp_path / "external.yaml"
    external.write_text(
        policy_file(tmp_path, "comment").read_text() + "publish:\n  on_block: request_changes\n"
        "threads:\n  resolve_on_fix: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "DEFAULT_AUTO_POLICY", external)
    monkeypatch.chdir(tmp_path / "repo")
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
    with pytest.warns(FutureWarning):
        result = runner.invoke(
            cli_module.app,
            ["run", "--target", "42", "--out", str(out), "--publish", "github-review", "--json"],
        )
    assert result.exit_code == 1, result.output
    process = json.loads((out / "process.json").read_text())
    assert process["effective_policy"]["source"] == "external"
    assert (
        calls[0]["publish_policy"] == PublishPolicy()
        and calls[0]["thread_policy"] == ThreadPolicy()
    )
    assert calls[0]["policy_source"] == "default"


def test_review_dry_run_tolerates_a_malformed_base_policy_but_publish_fails_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_policy import policy_repo

    target = policy_repo(tmp_path / "repo", repository_policy="drop: {agreement_at_most: -1}\n")
    monkeypatch.chdir(tmp_path / "repo")
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: target)
    dispatched: list[bool] = []

    async def forbidden(**kwargs: object) -> None:
        dispatched.append(True)
        raise AssertionError("review dispatched with an invalid policy")

    monkeypatch.setattr(cli_module, "_execute_pipeline", forbidden)
    result = runner.invoke(
        cli_module.app, ["review", "--target", "42", "--publish", "--out", str(tmp_path / "runs")]
    )
    assert result.exit_code == 2, result.output
    assert "invalid_policy:" in result.stderr and dispatched == []


@pytest.mark.parametrize("publish_block", ["", "publish:\n  channels: [checks]\n"])
def test_run_publication_request_honors_channels_and_retains_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publish_block: str
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    patch_pipeline(monkeypatch, artifacts)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: artifacts.target)
    monkeypatch.setattr(
        cli_module, "publish_review", lambda **_: pytest.fail("review must be disabled")
    )
    policy = policy_file(tmp_path, "none" if not publish_block else "comment")
    policy.write_text(policy.read_text() + publish_block)
    out = tmp_path / "channels-result"
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
    summary = json.loads((out / "summary.json").read_text())
    assert summary["publish"]["channels"] == ["checks"]
    assert summary["publish"]["inline_policy"]["body_only_count"] == len(artifacts.merged.groups)
    assert "Review complete." in summary["markdown"]
    process = json.loads((out / "process.json").read_text())
    assert process["runtime"]["publish"] == "none"


def test_interactive_review_passes_channel_and_inline_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    patch_pipeline(monkeypatch, artifacts)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _: artifacts.target)
    from test_publish_policy import strict_policy

    policy = strict_policy(publish={"channels": ["checks"], "inline": {"max_comments": 0}})
    monkeypatch.setattr(
        cli_module,
        "resolve_auto_policy",
        lambda *_, **__: EffectivePolicy(policy, "repository", "base"),
    )
    calls: list[dict[str, object]] = []

    def publish(**kwargs: object) -> PublishResult:
        calls.append(kwargs)
        return PublishResult(
            review_url=None, inline_count=0, body_fallback_count=0, state="skipped"
        )

    monkeypatch.setattr(cli_module, "publish_review", publish)
    result = runner.invoke(
        cli_module.app, ["review", "--target", "42", "--publish", "--out", str(tmp_path / "runs")]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["publish_policy"] == policy.publish


def test_external_snapshot_keeps_legacy_switch_but_ignores_new_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_publish_policy import strict_policy

    artifacts = saved_run(tmp_path, monkeypatch)
    artifacts.run.save_policy(
        EffectivePolicy(
            strict_policy(
                publish={
                    "channels": ["checks"],
                    "inline": {"max_comments": 0},
                },
                threads={"resolve_on_fix": False},
            ),
            "external",
            "external.yaml",
        )
    )
    monkeypatch.setattr(cli_module, "_commit_available", lambda *_: False)
    selected = cli_module._publication_policy(artifacts.run, artifacts.target, cwd=tmp_path)
    assert selected.policy.publish == PublishPolicy()
    assert selected.policy.threads.resolve_on_fix is True
    assert selected.source == "default" and selected.verified is False
