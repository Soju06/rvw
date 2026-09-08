"""CLI adapters preserve publication-language failures and explicit fallback facts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cli_phase5 import fixture_artifacts, policy_file
from typer.testing import CliRunner

import rvw.cli as cli
from rvw.pipeline import PipelineArtifacts
from rvw.presentation import PresentationConfig
from rvw.publish import PublicationLanguageMismatch, PublishResult


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize("fallback", ["none", "cli", "policy"])
def test_run_and_auto_record_language_result_and_preserve_outcome_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, fallback: str
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    policy = policy_file(tmp_path, "comment")
    if fallback == "policy":
        policy.write_text(policy.read_text() + "allow_language_fallback: true\n")
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)
    monkeypatch.setattr(cli, "provision_checkout", lambda **_: Path.cwd())
    monkeypatch.setattr(
        cli, "load_repo_presentation", lambda *_, **__: PresentationConfig(locale="ko")
    )

    async def execute(**kwargs: object) -> PipelineArtifacts:
        return artifacts

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    publications: list[bool] = []

    def publish(**kwargs: object) -> PublishResult:
        allowed = kwargs["allow_language_fallback"]
        assert isinstance(allowed, bool)
        publications.append(allowed)
        if not allowed:
            raise PublicationLanguageMismatch("ko")
        return PublishResult(
            review_url="https://github.com/owner/repo/pull/42#review",
            inline_count=1,
            body_fallback_count=0,
            state="commented",
            language_fallback_used=True,
        )

    monkeypatch.setattr(cli, "publish_review", publish)
    out = tmp_path / "result"
    args = [command, "--target", "42", "--policy", str(policy), "--out", str(out), "--json"]
    args += ["--publish", "github-review"] if command == "run" else ["--publish"]
    if fallback == "cli":
        args += ["--allow-language-fallback"]
    result = CliRunner().invoke(cli.app, args)
    assert publications == [fallback != "none"]
    process = json.loads((out / "process.json").read_text())
    summary = json.loads((out / "summary.json").read_text())
    assert json.loads(result.stdout) == process
    assert summary["findings"]["blocker"] > 0
    assert summary["verdicts"]["CONFIRMED"] > 0
    assert summary["presentation"]["locale"] == "ko"
    assert "검토를 마쳤습니다" in summary["markdown"]
    if fallback == "none":
        assert result.exit_code == 3
        assert process["failure"]["code"] == "publication_language_mismatch"
        assert process["publication_failure"] == "publication_language_mismatch"
        assert summary["publication_failure"] == "publication_language_mismatch"
        assert not process["language_fallback_used"]
        assert not summary["language_fallback_used"]
    else:
        assert result.exit_code == 1  # Existing policy BLOCK survives fallback.
        assert process["failure"] is None
        assert process["language_fallback_used"]
        assert summary["language_fallback_used"]
        assert process["publication_failure"] is None
        assert summary["publication_failure"] is None
