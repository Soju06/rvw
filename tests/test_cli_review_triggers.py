"""Repository review policy stops CLI execution before discovery."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_cli_phase5 import fixture_artifacts
from test_cli_review import registry_root as registry_root
from typer.testing import CliRunner

import rvw.cli as cli
from rvw.policy import EffectivePolicy, packaged_policy
from rvw.presentation import PresentationConfig
from rvw.summary import ExecutionSummary
from rvw.target import ResolvedTarget

runner = CliRunner()
_read_policy_api = cli._read_execution_repository_policy


@pytest.fixture
def release() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        pr_number=1772,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["a.py"],
        diff="unused",
        pr_author="github-actions[bot]",
        pr_head_branch="changeset-release/main",
        pr_base_branch="main",
        pr_title="chore(release): version packages",
        pr_labels=["🧹 Chore"],
    )


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    raw = packaged_policy().policy.model_dump(mode="json")
    raw["publish_state"] = "none"
    # Omit explicit channels so the legacy switch still selects checks-only publication.
    raw["publish"].pop("channels")
    raw["triggers"] = {
        "rules": [
            {
                "name": "changesets-release",
                "authors": ["github-actions[bot]"],
                "head_branches": ["changeset-release/*"],
            }
        ]
    }
    path = tmp_path / "auto.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, release: ResolvedTarget) -> None:
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: release)
    monkeypatch.setattr(cli, "load_repo_presentation", lambda *_, **__: PresentationConfig())
    monkeypatch.setattr(cli, "DEFAULT_RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "publish_review", lambda **_: pytest.fail("trigger test published"))


@pytest.mark.parametrize("command", ["run", "auto"])
def test_policy_skip_exits_zero_and_never_discovers(monkeypatch, tmp_path, policy, command):
    async def forbidden(**_):
        pytest.fail("skipped PR ran discovery")

    monkeypatch.setattr(cli, "_execute_pipeline", forbidden)
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app,
        [
            command,
            "--target",
            "1772",
            "--policy",
            str(policy),
            "--repo-dir",
            str(tmp_path),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "review skipped by repository policy: changesets-release"
    summary = json.loads((out / "summary.json").read_text())
    assert summary["trigger"]["skipped"] is True
    assert summary["trigger"]["rule"] == "changesets-release"
    assert "skipped" in summary["markdown"].lower()
    assert json.loads((out / "process.json").read_text())["exit_code"] == 0


@pytest.mark.parametrize("command", ["run", "auto", "review"])
@pytest.mark.parametrize("locale", ["en", "ko"])
@pytest.mark.parametrize("reason", ["rule", "draft", "allowlist"])
def test_skip_output_and_summary_follow_presentation_locale(
    monkeypatch, tmp_path, policy, release, command, locale, reason
):
    from rvw.policy import load_policy

    raw = yaml.safe_load(policy.read_text())
    raw["publish"]["inline"] = {"severity_at_least": "warning", "max_comments": 0}
    policy.write_text(yaml.safe_dump(raw))
    if reason == "draft":
        release = release.model_copy(update={"pr_draft": True})
    elif reason == "allowlist":
        raw = yaml.safe_load(policy.read_text())
        raw["triggers"] = {"mode": "allowlist", "rules": [{"name": "human", "authors": ["human"]}]}
        policy.write_text(yaml.safe_dump(raw))
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: release)
    monkeypatch.setattr(
        cli, "load_repo_presentation", lambda *_, **__: PresentationConfig(locale=locale)
    )
    monkeypatch.setattr(
        cli,
        "resolve_auto_policy",
        lambda *_, **__: EffectivePolicy(load_policy(policy), "repository", "base:auto.yaml"),
    )

    async def forbidden(**_):
        pytest.fail("skipped PR ran discovery")

    monkeypatch.setattr(cli, "execute_pipeline", forbidden)
    monkeypatch.setattr(cli, "publish_review", lambda **_: pytest.fail("skipped PR published"))
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app,
        [command, "--target", "1772", "--repo-dir", str(tmp_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    reasons = {
        "en": {
            "rule": "changesets-release",
            "draft": "draft",
            "allowlist": "no-matching-allowlist-rule",
        },
        "ko": {
            "rule": "changesets-release",
            "draft": "초안 PR",
            "allowlist": "일치하는 허용 목록 규칙 없음",
        },
    }
    prefix = (
        "review skipped by repository policy"
        if locale == "en"
        else "저장소 정책에 따라 리뷰를 건너뜀"
    )
    expected = f"{prefix}: {reasons[locale][reason]}"
    assert result.stdout.strip() == expected
    summary_path = next(out.glob("*/summary.json")) if command == "review" else out / "summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["markdown"] == expected
    assert summary["presentation"]["locale"] == locale
    assert json.loads((summary_path.parent / "presentation.json").read_text())["locale"] == locale
    assert summary["trigger"]["skipped"] is True
    assert summary["trigger"]["rule"] == ("changesets-release" if reason == "rule" else None)
    assert summary["trigger"]["mode"] == ("allowlist" if reason == "allowlist" else "denylist")
    assert summary["publish"]["channels"] == ["checks"]
    assert summary["publish"]["inline_policy"] == {
        "severity_at_least": "warning",
        "max_comments": 0,
        "body_only_count": 0,
    }


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize("force", [False, True])
def test_force_and_non_pr_facts_survive_summary_replacement(
    monkeypatch, tmp_path, policy, release, command, force
):
    from rvw.synthesis import SynthesisFacts

    raw = yaml.safe_load(policy.read_text())
    raw["publish"]["inline"] = {"severity_at_least": "warning", "max_comments": 0}
    policy.write_text(yaml.safe_dump(raw))
    if not force:
        release = release.model_copy(update={"kind": "commit", "pr_number": None})
        monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: release)
    artifacts = fixture_artifacts(tmp_path, adjudicated=False)
    artifacts = replace(
        artifacts,
        summary=cli._artifact_summary(artifacts).model_copy(
            update={"synthesis": SynthesisFacts(status="disabled")}
        ),
    )

    async def execute(**kwargs):
        run = kwargs["run_handle"]
        (run.dir / "summary.json").write_text(ExecutionSummary().model_dump_json())
        return replace(artifacts, run=run, target=release)

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    out = tmp_path / "out"
    args = [
        command,
        "--target",
        "1772",
        "--policy",
        str(policy),
        "--repo-dir",
        str(tmp_path),
        "--out",
        str(out),
        "--json",
    ]
    if force:
        args.append("--force-review")
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    summary = json.loads((out / "summary.json").read_text())
    trigger = summary["trigger"]
    assert trigger["skipped"] is False
    assert trigger["bypassed"] == ("force" if force else None)
    assert trigger["not_applicable"] is not force
    assert summary["publish"]["channels"] == ["checks"]
    assert summary["publish"]["inline_policy"] == {
        "severity_at_least": "warning",
        "max_comments": 0,
        "body_only_count": len(artifacts.merged.groups),
    }
    assert summary["synthesis"]["status"] == "disabled"


def test_interactive_review_policy_uses_checkout_and_skips_before_registry(
    monkeypatch, tmp_path, policy
):
    seen = []

    def select(target, *, cwd, **_):
        from rvw.policy import load_policy

        seen.append(cwd)
        return EffectivePolicy(load_policy(policy), "repository", "base:.rvw/policies/auto.yaml")

    monkeypatch.setattr(cli, "resolve_auto_policy", select)
    monkeypatch.setattr(cli, "_load_registry_root", lambda _: pytest.fail("loaded registry"))
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app, ["review", "--target", "1772", "--repo-dir", str(tmp_path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert seen == [tmp_path]
    assert result.stdout.strip() == "review skipped by repository policy: changesets-release"
    summary_path = next(out.glob("*/summary.json"))
    assert json.loads(summary_path.read_text())["trigger"]["skipped"] is True


def test_interactive_review_invalid_policy_keeps_machine_reason(monkeypatch, tmp_path):
    def invalid(*_, **__):
        raise ValueError("triggers: invalid title regex")

    monkeypatch.setattr(cli, "resolve_auto_policy", invalid)
    result = runner.invoke(
        cli.app,
        ["review", "--target", "1772", "--repo-dir", str(tmp_path), "--out", str(tmp_path / "out")],
    )
    assert result.exit_code == 2
    assert "invalid_policy" in result.stderr


def snapshot(target, **trigger):
    from rvw.summary import TriggerFacts

    return json.dumps(
        {
            "repo": target.repo,
            "pr": target.pr_number,
            "base": target.base_sha,
            "head": target.head_sha,
            "trigger": TriggerFacts(**trigger).model_dump(),
        }
    )


@pytest.mark.parametrize("policy_error", [None, "policy_invalid"])
def test_worker_snapshot_preserves_bypass_and_trigger_error(
    monkeypatch, tmp_path, release, policy, policy_error
):
    if policy_error:
        raw = yaml.safe_load(policy.read_text())
        raw["triggers"] = {"mode": "broken"}
        policy.write_text(yaml.safe_dump(raw))
    artifacts = fixture_artifacts(tmp_path, adjudicated=False)

    async def execute(**kwargs):
        return replace(artifacts, run=kwargs["run_handle"], target=release)

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    # The Worker always selects the repository source with --policy auto.
    import rvw.policy as policies

    original = policies.resolve_auto_policy

    def selected(target, *, cwd, **kwargs):
        effective = original(
            target,
            cwd=cwd,
            policy=policy,
            ignore_invalid_triggers=kwargs.get("ignore_invalid_triggers", False),
        )
        return EffectivePolicy(effective.policy, "repository", "base:.rvw/policies/auto.yaml")

    monkeypatch.setattr(cli, "resolve_auto_policy", selected)
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--target",
            "1772",
            "--repo-dir",
            str(tmp_path),
            "--out",
            str(out),
            "--force-review",
        ],
        env={
            "RVW_TRIGGER_SNAPSHOT": snapshot(
                release, bypassed="rerequested", policy_error=policy_error
            )
        },
    )
    assert result.exit_code == 0, result.output
    facts = json.loads((out / "summary.json").read_text())["trigger"]
    assert facts["bypassed"] == "rerequested"
    assert facts["policy_error"] == policy_error


def test_worker_snapshot_rejects_anchor_mismatch_before_discovery(
    monkeypatch, tmp_path, release, policy
):
    async def forbidden(**_):
        pytest.fail("mismatched snapshot ran discovery")

    monkeypatch.setattr(cli, "_execute_pipeline", forbidden)
    changed = release.model_copy(update={"head_sha": "c" * 40})
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--target",
            "1772",
            "--repo-dir",
            str(tmp_path),
            "--policy",
            str(policy),
            "--out",
            str(tmp_path / "out"),
        ],
        env={"RVW_TRIGGER_SNAPSHOT": snapshot(changed, bypassed="rerequested")},
    )
    assert result.exit_code == 2, result.output
    assert "trigger snapshot anchor mismatch" in result.stderr


def test_remote_inline_review_reads_policy_at_base_sha(monkeypatch, tmp_path, release, policy):
    import base64

    monkeypatch.setattr(cli, "_read_execution_repository_policy", _read_policy_api)
    monkeypatch.setattr(cli, "_commit_available", lambda *_: False)
    monkeypatch.setattr(cli, "resolve_auto_policy", lambda *_, **__: packaged_policy())
    seen = []

    class API:
        def rest(self, method, path):
            seen.append((method, path))
            return {"type": "file", "content": base64.b64encode(policy.read_bytes()).decode()}

    monkeypatch.setattr(cli, "GhCliClient", API)
    result = runner.invoke(
        cli.app,
        [
            "review",
            "--target",
            "1772",
            "--discovery-mode",
            "inline",
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == [
        ("GET", f"repos/owner/repo/contents/.rvw/policies/auto.yaml?ref={release.base_sha}")
    ]
    assert result.stdout.strip() == "review skipped by repository policy: changesets-release"


def test_snapshot_trigger_fallback_preserves_invalid_publication_failure(
    monkeypatch, tmp_path, release
):
    from rvw.policy import load_policy

    invalid_path = tmp_path / "invalid.yaml"
    raw = packaged_policy().policy.model_dump(mode="json")
    raw["triggers"] = {"mode": "broken"}
    raw["publish"] = {"on_pass": "approve"}
    invalid_path.write_text(yaml.safe_dump(raw))

    def selected(*_, **kwargs):
        return EffectivePolicy(
            load_policy(
                invalid_path, ignore_invalid_triggers=kwargs.get("ignore_invalid_triggers", False)
            ),
            "repository",
            "base:.rvw/policies/auto.yaml",
        )

    monkeypatch.setattr(cli, "resolve_auto_policy", selected)
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app,
        ["run", "--target", "1772", "--repo-dir", str(tmp_path), "--out", str(out)],
        env={"RVW_TRIGGER_SNAPSHOT": snapshot(release, policy_error="policy_invalid")},
    )
    assert result.exit_code == 2, result.output
    assert "publish_policy_invalid" in result.stderr
    assert (
        json.loads((out / "summary.json").read_text())["trigger"]["policy_error"]
        == "policy_invalid"
    )


@pytest.mark.parametrize("kind", ["pr", "commit", "uncommitted"])
def test_review_pause_persists_force_or_not_applicable(
    monkeypatch, tmp_path, release, policy, kind, registry_root
):
    from rvw.policy import load_policy

    target = release.model_copy(update={"kind": kind, "pr_number": 1772 if kind == "pr" else None})
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: target)
    monkeypatch.setattr(
        cli,
        "resolve_auto_policy",
        lambda *_, **__: EffectivePolicy(load_policy(policy), "repository", "base:auto.yaml"),
    )
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)
        (kwargs["run_handle"].dir / "summary.json").write_text(ExecutionSummary().model_dump_json())
        return None

    monkeypatch.setattr(cli, "execute_pipeline", execute)
    out = tmp_path / "out"
    args = [
        "review",
        "--target",
        "1772",
        "--repo-dir",
        str(tmp_path),
        "--registry",
        str(registry_root),
        "--out",
        str(out),
        "--pause",
    ]
    if kind == "pr":
        args.append("--force-review")
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    facts = json.loads(next(out.glob("*/summary.json")).read_text())["trigger"]
    assert facts["bypassed"] == ("force" if kind == "pr" else None)
    assert facts["not_applicable"] is (kind != "pr")


def test_remote_base_policy_precedes_invalid_external_policy(
    monkeypatch, tmp_path, release, policy
):
    from rvw.policy import load_policy

    calls = []

    def resolve(*_, **kwargs):
        calls.append(kwargs["allow_external"])
        if kwargs["allow_external"]:
            raise ValueError("invalid legacy external policy")
        return packaged_policy()

    monkeypatch.setattr(cli, "resolve_auto_policy", resolve)
    monkeypatch.setattr(cli, "_commit_available", lambda *_: False)
    selected = EffectivePolicy(load_policy(policy), "repository", "base:auto.yaml")
    monkeypatch.setattr(cli, "_read_execution_repository_policy", lambda *_, **__: selected)
    # A title-only rule still needs repository lookup without branch metadata.
    release = release.model_copy(update={"pr_head_branch": None})
    assert cli._resolve_execution_policy(release, cwd=tmp_path) is selected
    assert calls == [False]
