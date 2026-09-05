from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import rvw.cli as cli
from rvw.discover import DiscoverResult
from rvw.merge import MergeResult
from rvw.pipeline import PipelineArtifacts
from rvw.policy import PolicyNotFound
from rvw.store import RunStore
from rvw.summary import CoverageTotals, ReviewStatus, RunSummary
from rvw.target import ResolvedTarget

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "DEFAULT_RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "provision_checkout", lambda **_: Path.cwd())


@pytest.fixture
def resolved() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        pr_number=42,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["a.py"],
        diff="diff --git a/a.py b/a.py\n",
    )


@pytest.fixture
def artifacts(tmp_path: Path, resolved: ResolvedTarget) -> PipelineArtifacts:
    run = RunStore(tmp_path / "runs").create(resolved)
    return PipelineArtifacts(
        run=run,
        target=resolved,
        discovered=DiscoverResult(lane_results={}, findings=[], coverage=[]),
        merged=MergeResult(groups=[], sites=[], pattern_folds=[], region_folds=[]),
        outcome=None,
        report_md="# report\n",
        report_path=run.dir / "report.md",
        summary=RunSummary(
            run_id=run.run_id,
            status=ReviewStatus.FAILED,
            coverage_totals=CoverageTotals(dispatched=1, valid=0, findings=0),
            failed_lanes=[],
            error=None,
        ),
    )


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "promote_to_blocker: {agreement_at_least: 2, severity_at_least: warning}\n"
        "drop: {agreement_at_most: 1, severity_at_most: suggestion}\n"
        "block_when: {severity_at_least: blocker, confirmed_only: true}\n"
        "publish_state: none\n"
    )
    return path


def test_auto_failed_review_never_passes(
    monkeypatch: pytest.MonkeyPatch, artifacts: PipelineArtifacts, policy: Path
) -> None:
    async def execute(**kwargs: object) -> PipelineArtifacts:
        return artifacts

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)
    result = runner.invoke(cli.app, ["auto", "--target", "42", "--policy", str(policy), "--json"])
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["failure"]["code"] == "review_failed"
    assert payload["failure"]["detail"]
    paths = list(artifacts.run.dir.parent.rglob("process.json"))
    assert paths
    assert json.loads(paths[0].read_text())["status"] == "infra_failed"


@pytest.mark.parametrize(
    "error,expected",
    [(RuntimeError("checkout runtime broke"), 3), (PolicyNotFound(Path("missing.yaml")), 2)],
)
def test_auto_exceptions_cannot_masquerade_as_block(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: PipelineArtifacts,
    policy: Path,
    error: Exception,
    expected: int,
) -> None:
    async def execute(**kwargs: object) -> PipelineArtifacts:
        raise error

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)
    result = runner.invoke(cli.app, ["auto", "--target", "42", "--policy", str(policy), "--json"])
    assert result.exit_code == expected, result.output
    assert json.loads(result.stdout)["status"] in {"invalid", "infra_failed"}


@pytest.mark.parametrize("command", ["run", "auto"])
def test_anchor_mismatch_writes_contract_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resolved: ResolvedTarget,
    command: str,
) -> None:
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: resolved)

    async def forbidden(**kwargs: object) -> None:
        pytest.fail("anchor mismatch dispatched runtime")

    monkeypatch.setattr(cli, "_execute_pipeline", forbidden)
    out = tmp_path / "result"
    result = runner.invoke(
        cli.app,
        [
            command,
            "--target",
            "42",
            "--base-ref",
            "c" * 40,
            "--head-ref",
            resolved.head_sha,
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    process = json.loads((out / "process.json").read_text())
    assert process["failure"]["code"] == "target_anchor_mismatch"
    assert process["target"]["head"] == resolved.head_sha
    assert process["status"] == "invalid"
    assert_manifest(out, process)


def assert_manifest(out: Path, process: dict) -> None:
    actual = {
        p.relative_to(out).as_posix(): p.stat().st_size for p in out.rglob("*") if p.is_file()
    }
    assert {a["path"]: a["size_bytes"] for a in process["artifacts"]} == actual
    assert {"process.json", "summary.json", "run.log", "environment.txt"} <= actual.keys()


def test_publication_exception_is_infrastructure_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifacts: PipelineArtifacts,
    policy: Path,
) -> None:
    assert artifacts.summary is not None
    good = replace(
        artifacts,
        summary=artifacts.summary.model_copy(
            update={
                "status": ReviewStatus.COMPLETE,
                "coverage_totals": CoverageTotals(dispatched=1, valid=1, findings=0),
            }
        ),
    )

    async def execute(**kwargs: object) -> PipelineArtifacts:
        return good

    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: good.target)
    monkeypatch.setattr(cli, "_execute_pipeline", execute)

    def fail(**kwargs: object) -> None:
        raise RuntimeError("publication broke")

    monkeypatch.setattr(cli, "publish_review", fail)
    result = runner.invoke(
        cli.app, ["auto", "--target", "42", "--policy", str(policy), "--publish", "--json"]
    )
    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["failure"]["code"] == "publication_failed"


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize(
    "option,value", [("--deadline", "0"), ("--replicas", "wat"), ("--discovery-mode", "bad")]
)
def test_usage_errors_persist_invalid_contract(
    tmp_path: Path, command: str, option: str, value: str
) -> None:
    out = tmp_path / "result"
    result = runner.invoke(
        cli.app, [command, "--target", "42", "--out", str(out), option, value, "--json"]
    )
    assert result.exit_code == 2
    process = json.loads((out / "process.json").read_text())
    assert process["failure"]["code"] == "invalid_input"
    assert_manifest(out, process)


def test_failed_review_does_not_evaluate_policy(
    monkeypatch: pytest.MonkeyPatch, artifacts: PipelineArtifacts, policy: Path
) -> None:
    async def execute(**kwargs: object) -> PipelineArtifacts:
        return artifacts

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)

    def forbidden(*args: object) -> None:
        pytest.fail("a failed review cannot reach policy evaluation")

    monkeypatch.setattr(cli, "evaluate", forbidden)
    result = runner.invoke(cli.app, ["auto", "--target", "42", "--policy", str(policy), "--json"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["failure"]["code"] == "review_failed"


def test_supervisor_continues_after_log_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rvw.store import finalize_process, initialize_process

    out = tmp_path / "result"
    initialize_process(out, target_spec="42")
    original_open = Path.open

    def failed_log(path: Path, *args: Any, **kwargs: Any):
        if path == out / "run.log":
            raise PermissionError("log unavailable")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failed_log)
    result = finalize_process(out, failure_code="timed_out", failure_detail="deadline")
    assert result.failure is not None and result.failure.code == "timed_out"
    assert json.loads((out / "process.json").read_text())["failure"]["code"] == "timed_out"
    assert (out / "environment.txt").is_file()


def test_entrypoint_setup_failure_preserves_process_contract(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    out = tmp_path / "result"
    code = (
        "import sys; from pathlib import Path; "
        "from rvw.container_entrypoint import run_entrypoint; "
        f"run_entrypoint(sys.argv[1:], template_path=Path({str(tmp_path / 'missing.toml')!r}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, "run", "--target", "42", "--out", str(out)],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3, result.stderr
    process = json.loads((out / "process.json").read_text())
    assert process["failure"]["code"] == "container_setup_failed"
    assert_manifest(out, process)


def test_versioned_schema_resources_match_python_contract() -> None:
    from importlib.resources import files

    from rvw.summary import ExecutionSummary, ProcessResult

    for name, model in [("process", ProcessResult), ("summary", ExecutionSummary)]:
        schema = json.loads(
            files("rvw").joinpath(f"resources/schemas/{name}.schema.json").read_text()
        )
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
    assert set(ProcessResult.model_fields) == {
        "schema_version",
        "run_id",
        "target",
        "status",
        "exit_code",
        "duration_ms",
        "command",
        "effective_policy",
        "lane_sources",
        "runtime",
        "failure",
        "artifacts",
        "sdk_observations",
    }


def test_supervisor_retains_nested_files_and_redacts_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rvw.store import finalize_process, initialize_process
    from rvw.summary import SDKObservations

    out = tmp_path / "result"
    _, process = initialize_process(out, target_spec="https://github.com/a/b/pull/42")
    artifact = out / "runtime/r1/raw.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(bytes(range(256)))
    (out / "run.log").write_text("Authorization: Bearer not-a-real-token\n")
    (out / "environment.txt").write_text("credential=fake-sensitive-value\n")
    monkeypatch.setenv("CODEX_API_KEY", "fake-sensitive-value")
    final = finalize_process(
        out,
        failure_code="timed_out",
        failure_detail="deadline expired",
        sdk_observations=SDKObservations(signal="SIGTERM", duration_ms=42),
    )
    assert final.run_id == process.run_id
    assert final.target.repo == "a/b"
    assert final.sdk_observations is not None and final.sdk_observations.signal == "SIGTERM"
    assert "not-a-real-token" not in (out / "run.log").read_text()
    assert "fake-sensitive-value" not in (out / "environment.txt").read_text()
    assert_manifest(out, final.model_dump(mode="json"))


@pytest.mark.parametrize(
    "updates",
    [
        {"status": "pass", "exit_code": 1, "failure": None},
        {"status": "infra_failed", "exit_code": 3, "failure": None},
        {"schema_version": 2},
        {"extra": True},
    ],
)
def test_process_contract_rejects_inconsistent_or_unknown_fields(
    tmp_path: Path, updates: dict
) -> None:
    from pydantic import ValidationError

    from rvw.store import initialize_process
    from rvw.summary import ProcessResult

    _, process = initialize_process(tmp_path / "out", target_spec="42")
    with pytest.raises(ValidationError):
        ProcessResult.model_validate({**process.model_dump(), **updates})


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize(
    "case,status,exit_code",
    [
        ("pass", "pass", 0),
        ("block", "block", 1),
        ("policy", "invalid", 2),
        ("target", "invalid", 2),
        ("runtime", "infra_failed", 3),
        ("checkout", "infra_failed", 3),
        ("publication", "infra_failed", 3),
    ],
)
def test_run_auto_exit_matrix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifacts: PipelineArtifacts,
    policy: Path,
    command: str,
    case: str,
    status: str,
    exit_code: int,
) -> None:
    from rvw.policy import AutoDecision

    assert artifacts.summary is not None
    good = replace(
        artifacts,
        summary=artifacts.summary.model_copy(
            update={
                "status": ReviewStatus.COMPLETE,
                "coverage_totals": CoverageTotals(dispatched=1, valid=1, findings=0),
            }
        ),
    )

    async def execute(**kwargs: object) -> PipelineArtifacts:
        if case == "runtime":
            raise RuntimeError("runtime exception")
        return good

    monkeypatch.setattr(cli, "_execute_pipeline", execute)

    def resolve(_: str) -> ResolvedTarget:
        if case == "target":
            raise ValueError("bad target")
        return good.target

    monkeypatch.setattr(cli, "_resolve_cli_target", resolve)
    if case == "checkout":

        def checkout(**kwargs: object) -> Path:
            raise RuntimeError("checkout exception")

        monkeypatch.setattr(cli, "provision_checkout", checkout)

    def publish(**kwargs: object) -> None:
        if case == "publication":
            raise RuntimeError("publication exception")

    monkeypatch.setattr(cli, "publish_review", publish)
    monkeypatch.setattr(
        cli,
        "evaluate",
        lambda *args: AutoDecision(
            verdict="BLOCK" if case == "block" else "PASS",
            blocking=["B1"] if case == "block" else [],
            dropped=[],
            promoted=[],
            considered=1,
        ),
    )
    out = tmp_path / "result"
    selected = policy if case != "policy" else tmp_path / "missing.yaml"
    args = [command, "--target", "42", "--policy", str(selected), "--out", str(out), "--json"]
    if case == "publication":
        args.extend(["--publish"] if command == "auto" else ["--publish", "github-comment"])
    result = runner.invoke(cli.app, args)
    assert result.exit_code == exit_code, result.output
    process = json.loads((out / "process.json").read_text())
    assert process["status"] == status
    assert process["exit_code"] == exit_code
    assert json.loads(result.stdout) == process
    assert_manifest(out, process)


def test_sigterm_finalizes_infrastructure_contract(tmp_path: Path) -> None:
    import os
    import signal
    import subprocess
    import sys
    import time

    out = tmp_path / "result"
    ready = tmp_path / "ready"
    script = f"""
import sys, time
from pathlib import Path
import rvw.cli as cli
from rvw.target import ResolvedTarget

def resolve(spec):
    Path({str(ready)!r}).touch()
    time.sleep(30)
cli._resolve_cli_target = resolve
cli.app()
"""
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    process = subprocess.Popen(
        [sys.executable, "-c", script, "run", "--target", "42", "--out", str(out)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        until = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < until:
            time.sleep(0.01)
        assert ready.exists()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 3, (stdout, stderr)
        result = json.loads((out / "process.json").read_text())
        assert result["status"] == "infra_failed"
        assert result["failure"]["code"] == "interrupted"
        assert_manifest(out, result)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_unexpected_adjudication_failure_summarizes_saved_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifacts: PipelineArtifacts,
    policy: Path,
) -> None:
    from rvw.discover import LaneCoverage, RunCoverage

    discovered = DiscoverResult(
        lane_results={},
        findings=[],
        coverage=[
            LaneCoverage(
                lane_id="fixture",
                dispatched=1,
                valid=1,
                findings=0,
                runs=[RunCoverage(replica=1, chunk=1, valid=True, findings=0, invalid_reason=None)],
            )
        ],
    )

    async def execute(**kwargs: Any) -> PipelineArtifacts:
        handle = kwargs["run_handle"]
        handle.save_discover(discovered)
        handle.save_merge(artifacts.merged)
        raise RuntimeError("unexpected adjudication failure")

    monkeypatch.setattr(cli, "_execute_pipeline", execute)
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)
    out = tmp_path / "result"
    result = runner.invoke(
        cli.app, ["run", "--target", "42", "--policy", str(policy), "--out", str(out)]
    )
    assert result.exit_code == 3
    summary = json.loads((out / "summary.json").read_text())
    assert summary["lanes"] == {"dispatched": 1, "valid": 1, "uncovered": 0}
    assert json.loads((out / "run.json").read_text())["status"] == "failed"
    assert_manifest(out, json.loads((out / "process.json").read_text()))


@pytest.mark.parametrize("target_spec", ["0", "https://github.com/owner/repo/pull/0"])
def test_invalid_pr_number_can_initialize_failure_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_spec: str
) -> None:
    def invalid(_: str) -> ResolvedTarget:
        raise ValueError("PR number must be positive")

    monkeypatch.setattr(cli, "_resolve_cli_target", invalid)
    out = tmp_path / "result"
    result = runner.invoke(cli.app, ["run", "--target", target_spec, "--out", str(out), "--json"])
    assert result.exit_code == 2, result.output
    assert json.loads((out / "process.json").read_text())["failure"]["code"] == "invalid_target"


def test_missing_gh_is_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rvw.target import TargetResolutionError

    def unavailable(_: str) -> ResolvedTarget:
        raise TargetResolutionError(
            ["gh", "pr", "view", "42"], "gh unavailable"
        ) from FileNotFoundError("gh")

    monkeypatch.setattr(cli, "_resolve_cli_target", unavailable)
    out = tmp_path / "result"
    result = runner.invoke(cli.app, ["run", "--target", "42", "--out", str(out), "--json"])
    assert result.exit_code == 3, result.output
    assert (
        json.loads((out / "process.json").read_text())["failure"]["code"]
        == "target_resolution_failed"
    )
