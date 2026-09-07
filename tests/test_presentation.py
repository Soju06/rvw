"""Base-anchored presentation snapshots and strict configuration failures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from rvw.presentation import PresentationConfig, PresentationConfigInvalid
from rvw.registry import load_repo_presentation
from rvw.store import RunStore
from rvw.target import ResolvedTarget


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def anchored(tmp_path: Path) -> tuple[Path, ResolvedTarget]:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "fixture@example.test")
    git(tmp_path, "config", "user.name", "Fixture")
    (tmp_path / ".rvw").mkdir()
    (tmp_path / ".rvw/config.yaml").write_text(
        "display_name: VOOY Review System\nshort_name: VOOY Review\nlocale: ko\nfooter: null\n"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / ".rvw/config.yaml").write_text("display_name: Head Override\nlocale: en\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "head")
    target = ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        pr_number=1,
        base_sha=base,
        head_sha=git(tmp_path, "rev-parse", "HEAD"),
        changed_paths=[".rvw/config.yaml"],
        diff="diff",
    )
    return tmp_path, target


@pytest.mark.parametrize(
    "payload",
    [
        {"display_name": " "},
        {"display_name": "a" * 81},
        {"short_name": "a" * 41},
        {"display_name": "a\nb"},
        {"short_name": "a\tb"},
        {"footer": "a\x00b"},
        {"display_name": "a\u202eb"},
        {"footer": "a" * 241},
        {"locale": "fr"},
        {"short_name": 12},
        {"unknown": True},
        {"footer": False},
    ],
)
def test_presentation_schema_rejects_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PresentationConfig.model_validate(payload)


def test_presentation_defaults_and_unicode_names() -> None:
    assert PresentationConfig().model_dump() == {
        "display_name": "rvw",
        "short_name": "rvw",
        "locale": "en",
        "footer": None,
    }
    assert (
        PresentationConfig(
            display_name="검토 시스템", short_name="검토", footer="담당자에게 문의하세요."
        ).short_name
        == "검토"
    )


def test_config_reads_base_not_head_or_worktree(anchored: tuple[Path, ResolvedTarget]) -> None:
    repo, target = anchored
    (repo / ".rvw/config.yaml").write_text("locale: invalid\n")
    assert load_repo_presentation(target, cwd=repo).display_name == "VOOY Review System"
    assert load_repo_presentation(target, cwd=repo).locale == "ko"
    with pytest.raises(PresentationConfigInvalid, match="presentation_config_invalid"):
        load_repo_presentation(target, cwd=repo, allow_worktree_rules=True)


def test_worktree_opt_in_has_same_non_sot_warning(anchored: tuple[Path, ResolvedTarget]) -> None:
    repo, target = anchored
    with pytest.warns(
        UserWarning,
        match="WARNING: .rvw rules loaded from the working tree via --allow-worktree-rules; this run is non-SoT.",
    ):
        config = load_repo_presentation(target, cwd=repo, allow_worktree_rules=True)
    assert config.display_name == "Head Override"


def test_absent_file_defaults_but_unavailable_base_fails(
    anchored: tuple[Path, ResolvedTarget],
) -> None:
    repo, target = anchored
    git(repo, "rm", ".rvw/config.yaml")
    git(repo, "commit", "-qm", "absent")
    absent = target.model_copy(update={"base_sha": git(repo, "rev-parse", "HEAD")})
    assert load_repo_presentation(absent, cwd=repo) == PresentationConfig()
    for base in [None, "f" * 40]:
        with pytest.raises(PresentationConfigInvalid):
            load_repo_presentation(target.model_copy(update={"base_sha": base}), cwd=repo)


@pytest.mark.parametrize(
    "raw", ["locale: [ko", "null", "[]", "display_name: 42", "locale: ko\nlocale: en\n"]
)
def test_malformed_config_fails_closed(anchored: tuple[Path, ResolvedTarget], raw: str) -> None:
    repo, target = anchored
    (repo / ".rvw/config.yaml").write_text(raw)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "invalid")
    target = target.model_copy(update={"base_sha": git(repo, "rev-parse", "HEAD")})
    with pytest.raises(PresentationConfigInvalid, match="presentation_config_invalid"):
        load_repo_presentation(target, cwd=repo)


def test_snapshot_replay_and_invalid_snapshot(anchored: tuple[Path, ResolvedTarget]) -> None:
    repo, target = anchored
    run = RunStore(repo / "runs").create(target)
    assert run.load_presentation() == PresentationConfig()
    snapshot = load_repo_presentation(target, cwd=repo)
    run.save_presentation(snapshot)
    (repo / ".rvw/config.yaml").write_text("locale: en\n")
    assert run.load_presentation() == snapshot
    (run.dir / "presentation.json").write_text('{"locale":"xx"}')
    with pytest.raises(PresentationConfigInvalid):
        run.load_presentation()


@pytest.mark.parametrize("command", ["run", "auto"])
def test_invalid_presentation_stops_before_runtime_and_records_contract(
    anchored: tuple[Path, ResolvedTarget], monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    import rvw.cli as cli

    repo, target = anchored
    (repo / ".rvw/config.yaml").write_text("locale: invalid\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "invalid")
    target = target.model_copy(update={"base_sha": git(repo, "rev-parse", "HEAD")})
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: target)

    async def forbidden(**kwargs: object) -> None:
        pytest.fail("invalid presentation must not dispatch a review")

    monkeypatch.setattr(cli, "_execute_pipeline", forbidden)
    out = repo / "result"
    result = CliRunner().invoke(
        cli.app, [command, "--target", "1", "--repo-dir", str(repo), "--out", str(out), "--json"]
    )
    assert result.exit_code == 2, result.output
    process = json.loads((out / "process.json").read_text())
    assert process["failure"]["code"] == "presentation_config_invalid"
    assert process["presentation"] == PresentationConfig().model_dump()


def test_resolved_presentation_is_shared_and_persisted_once(
    anchored: tuple[Path, ResolvedTarget], monkeypatch: pytest.MonkeyPatch
) -> None:
    import rvw.cli as cli
    from rvw.discover import DiscoverResult, LaneCoverage, RunCoverage
    from rvw.merge import merge
    from rvw.pipeline import PipelineArtifacts
    from rvw.summary import summarize_run

    repo, target = anchored
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: target)
    monkeypatch.setattr(cli, "DEFAULT_AUTO_POLICY", repo / "no-external-policy")
    calls = 0

    def resolve(*args: object, **kwargs: object) -> PresentationConfig:
        nonlocal calls
        calls += 1
        return load_repo_presentation(target, cwd=repo)

    monkeypatch.setattr(cli, "load_repo_presentation", resolve)

    async def execute(**kwargs: object) -> PipelineArtifacts:
        from rvw.store import RunHandle

        run = kwargs["run_handle"]
        assert isinstance(run, RunHandle)
        assert kwargs["presentation"] == run.load_presentation()
        (repo / ".rvw/config.yaml").write_text("locale: en\n")
        discovered = DiscoverResult(
            lane_results={},
            findings=[],
            coverage=[
                LaneCoverage(
                    lane_id="fixture",
                    dispatched=1,
                    valid=1,
                    findings=0,
                    runs=[
                        RunCoverage(replica=1, chunk=1, valid=True, findings=0, invalid_reason=None)
                    ],
                )
            ],
        )
        return PipelineArtifacts(
            run=run,
            target=target,
            discovered=discovered,
            merged=merge([], lane_tiers={}),
            outcome=None,
            report_md="",
            report_path=run.dir / "report.md",
            summary=summarize_run(run.run_id, discovered),
            presentation=run.load_presentation(),
        )

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    out = repo / "result"
    result = CliRunner().invoke(
        cli.app, ["run", "--target", "1", "--repo-dir", str(repo), "--out", str(out), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert calls == 1
    presentation = json.loads((out / "presentation.json").read_text())
    assert presentation["locale"] == "ko"
    assert json.loads((out / "process.json").read_text())["presentation"] == presentation
    assert json.loads((out / "summary.json").read_text())["presentation"] == presentation


def test_config_resolution_from_repository_subdirectory(
    anchored: tuple[Path, ResolvedTarget],
) -> None:
    repo, target = anchored
    nested = repo / "src"
    nested.mkdir()
    assert load_repo_presentation(target, cwd=nested).locale == "ko"


def test_config_directory_is_not_treated_as_missing(anchored: tuple[Path, ResolvedTarget]) -> None:
    repo, target = anchored
    path = repo / ".rvw/config.yaml"
    path.unlink()
    path.mkdir()
    (path / "entry.yaml").write_text("locale: ko\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "invalid directory")
    target = target.model_copy(update={"base_sha": git(repo, "rev-parse", "HEAD")})
    with pytest.raises(PresentationConfigInvalid):
        load_repo_presentation(target, cwd=repo)
