from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner, Result

import rvw.cli as cli_module
import rvw.pipeline as pipeline_module
import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import MergeResult
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Verdict
from rvw.store import RunStore
from rvw.target import ResolvedTarget

runner = CliRunner()


def test_review_rejects_invalid_host_concurrency_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fail_if_called(**_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli_module, "_review_pipeline", fail_if_called)

    result = runner.invoke(
        cli_module.app,
        ["review", "--target", "HEAD"],
        env={"RVW_HOST_CONCURRENCY": "abc"},
    )

    assert result.exit_code == cli_module.EXIT_USER_ERROR
    assert "RVW_HOST_CONCURRENCY" in result.stderr
    assert called is False


def pr_target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/app.py"],
        diff=(
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
        pr_number=42,
        pr_title="Change app",
        pr_body="Body",
    )


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    lane_root = root / "lanes" / "base"
    lane_root.mkdir(parents=True)
    (root / "layers.yaml").write_text(
        """layers:
  - id: base
    tier: base
    lanes: [test-lane]
""",
        encoding="utf-8",
    )
    (lane_root / "test-lane.md").write_text(
        """---
lane: test-lane
tier: base
cost: light
rules:
  - test/rule
---

# test lane

Find the fixture issue.
""",
        encoding="utf-8",
    )
    return root


class FakeRuntime:
    name = "fake"

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
    ) -> RunResult[RuntimeLaneOutput]:
        del prompt, deadline_seconds
        replica = int(run_dir.name.removeprefix("r"))
        return RunResult(
            lane_id=lane.id,
            replica=replica,
            status=RunStatus.VALID,
            output=RuntimeLaneOutput(
                verdict="findings",
                findings=[
                    RuntimeFinding(
                        rule_id="test/rule",
                        file="src/app.py",
                        line=1,
                        severity=Severity.WARNING,
                        body="fixture finding",
                    )
                ],
            ),
            invalid_reason=None,
            wall_seconds=0.01,
            artifact_dir=run_dir,
        )


@pytest.fixture
def patched_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve_target(spec: str, *, cwd: Path) -> ResolvedTarget:
        del spec, cwd
        return pr_target()

    async def fake_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        del kwargs
        return AdjudicationOutcome(
            verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
            reasons={group.key: "verified" for group in merged.groups},
            evidence={group.key: "new" for group in merged.groups},
            replica_votes={group.key: [Verdict.CONFIRMED] * 3 for group in merged.groups},
            unresolved=[],
            coerced_rejections=0,
        )

    monkeypatch.setattr(cli_module, "resolve_target", fake_resolve_target)
    monkeypatch.setattr(cli_module, "CodexRuntime", FakeRuntime)
    monkeypatch.setattr(cli_module, "adjudicate", fake_adjudicate)


def invoke_review(
    out_root: Path, registry_root: Path, *extra: str
) -> tuple[Result, dict[str, object]]:
    result = runner.invoke(
        cli_module.app,
        [
            "review",
            "--target",
            "42",
            "--registry",
            str(registry_root),
            "--out",
            str(out_root),
            *extra,
        ],
    )
    payload = json.loads(result.stdout) if "--json" in extra and result.exit_code == 0 else {}
    return result, payload


@pytest.mark.parametrize(
    ("extra", "expected_discover", "expected_adjudicate", "expected_concurrency"),
    [
        ([], 1, 3, 8),
        (["--replicas", "2"], 2, 3, 8),
        (["--adjudicate-replicas", "1"], 1, 1, 8),
        (["--replicas", "3", "--concurrency", "4"], 3, 3, 4),
    ],
)
def test_review_split_replica_defaults_and_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
    expected_discover: int,
    expected_adjudicate: int,
    expected_concurrency: int,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_review_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli_module, "_review_pipeline", fake_review_pipeline)

    result = runner.invoke(cli_module.app, ["review", "--target", "HEAD", *extra])

    assert result.exit_code == 0, result.stdout
    assert calls[0]["discover_replicas"] == expected_discover
    assert calls[0]["adjudicate_replicas"] == expected_adjudicate
    assert calls[0]["concurrency"] == expected_concurrency


def test_review_cli_passes_command_host_gate_to_execute_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, registry_root: Path
) -> None:
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")
    calls: list[dict[str, object]] = []

    async def fake_execute_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli_module, "_command_host_gate", lambda: gate)
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _spec: pr_target())
    monkeypatch.setattr(cli_module, "execute_pipeline", fake_execute_pipeline)

    result = runner.invoke(
        cli_module.app,
        ["review", "--target", "HEAD", "--registry", str(registry_root)],
    )

    assert result.exit_code == 0, result.stdout
    assert calls[0]["host_gate"] is gate


def test_review_rejects_zero_concurrency_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_review_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli_module, "_review_pipeline", fake_review_pipeline)

    result = runner.invoke(
        cli_module.app,
        ["review", "--target", "HEAD", "--concurrency", "0"],
    )

    assert result.exit_code == 2
    assert calls == []


async def test_shared_pipeline_propagates_split_replicas_and_concurrency(
    tmp_path: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each stage must receive ITS OWN replica count: distinct values prove
    execute_pipeline cannot forward one count to both stages."""

    stage_calls: list[tuple[str, int, int]] = []
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")

    async def fake_discover(**kwargs: object) -> DiscoverResult:
        assert kwargs["host_gate"] is gate
        replicas = kwargs["replicas"]
        concurrency = kwargs["concurrency"]
        assert isinstance(replicas, int)
        assert isinstance(concurrency, int)
        stage_calls.append(("discover", replicas, concurrency))
        return DiscoverResult(lane_results={}, findings=[], coverage=[])

    async def fake_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        del merged
        assert kwargs["host_gate"] is gate
        replicas = kwargs["replicas"]
        concurrency = kwargs["concurrency"]
        assert isinstance(replicas, int)
        assert isinstance(concurrency, int)
        stage_calls.append(("adjudicate", replicas, concurrency))
        return AdjudicationOutcome(
            verdicts={},
            reasons={},
            evidence={},
            replica_votes={},
            unresolved=[],
            coerced_rejections=0,
        )

    registry, lanes_root = cli_module._load_registry_root(registry_root)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(pipeline_module, "discover", fake_discover)

    await pipeline_module.execute_pipeline(
        registry=registry,
        lanes_root=lanes_root,
        target=pr_target(),
        active_lanes=[],
        runtime=cast(Runtime, FakeRuntime()),
        adjudicator=fake_adjudicate,
        repo_dir=checkout,
        discover_replicas=2,
        adjudicate_replicas=5,
        concurrency=3,
        out_root=tmp_path / "runs",
        pause=False,
        dynamic_brief=None,
        host_gate=gate,
    )

    assert stage_calls == [("discover", 2, 3), ("adjudicate", 5, 3)]


def test_review_end_to_end_writes_all_stages_and_json_shape(
    tmp_path: Path, registry_root: Path, patched_pipeline: None
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result, payload = invoke_review(out_root, registry_root, "--repo-dir", str(repo_dir), "--json")

    assert result.exit_code == 0, result.stdout
    assert set(payload) == {"run_id", "report_path", "verdict_counts", "coverage_totals"}
    run_dir = out_root / str(payload["run_id"])
    assert {path.name for path in run_dir.iterdir()} >= {
        "target.json",
        "discover.json",
        "merge.json",
        "outcome.json",
        "report.md",
        "publish-payload.json",
    }
    assert payload["verdict_counts"] == {
        "CONFIRMED": 1,
        "REJECTED": 0,
        "UNCERTAIN": 0,
    }
    assert payload["coverage_totals"] == {"dispatched": 1, "valid": 1, "findings": 1}
    assert "## 확정 발견 (CONFIRMED)" in (run_dir / "report.md").read_text()


def test_pause_stops_after_merge_with_resume_hint(
    tmp_path: Path, registry_root: Path, patched_pipeline: None
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"

    result, _ = invoke_review(out_root, registry_root, "--pause")

    assert result.exit_code == 0, result.stdout
    assert "paused after MERGE — resume: rvw report --run" in result.stdout
    run_dir = next(out_root.iterdir())
    assert (run_dir / "merge.json").is_file()
    assert not (run_dir / "outcome.json").exists()
    assert not (run_dir / "report.md").exists()


def test_without_repo_dir_skips_adjudication_and_renders_unadjudicated(
    tmp_path: Path, registry_root: Path, patched_pipeline: None
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"

    result, _ = invoke_review(out_root, registry_root)

    assert result.exit_code == 0, result.stdout
    assert "--repo-dir" in result.stderr
    run_dir = next(out_root.iterdir())
    assert not (run_dir / "outcome.json").exists()
    assert "## 발견 (미판정)" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_report_resume_injects_synthesis_and_unknown_run_exits_one(
    tmp_path: Path, registry_root: Path, patched_pipeline: None
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"
    review_result, payload = invoke_review(out_root, registry_root, "--json")
    assert review_result.exit_code == 0
    synthesis = tmp_path / "synthesis.md"
    synthesis.write_text("정확히 이 종합을 사용합니다.\n\n둘째 문단.\n", encoding="utf-8")

    report_result = runner.invoke(
        cli_module.app,
        [
            "report",
            "--run",
            str(payload["run_id"]),
            "--out",
            str(out_root),
            "--synthesis",
            str(synthesis),
        ],
    )
    unknown = runner.invoke(
        cli_module.app,
        ["report", "--run", "missing-run", "--out", str(out_root)],
    )

    assert report_result.exit_code == 0, report_result.stdout
    report = Path(str(payload["report_path"])).read_text(encoding="utf-8")
    assert synthesis.read_text(encoding="utf-8") in report
    assert unknown.exit_code == 1
    assert "missing-run" in unknown.stderr


@pytest.mark.parametrize(
    ("command", "run_id"),
    [("report", "nested/run"), ("publish", "../x")],
)
def test_run_consumers_reject_invalid_run_ids_as_user_errors(
    tmp_path: Path,
    command: str,
    run_id: str,
) -> None:
    result = runner.invoke(
        cli_module.app,
        [command, "--run", run_id, "--out", str(tmp_path / "runs")],
    )

    assert result.exit_code == 2
    assert "invalid run ID" in result.stderr
    assert "Traceback" not in result.stderr


def test_publish_defaults_to_dry_run_and_non_pr_execute_is_user_error(
    tmp_path: Path,
    registry_root: Path,
    patched_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"
    review_result, payload = invoke_review(out_root, registry_root, "--json")
    assert review_result.exit_code == 0
    payload_path = out_root / str(payload["run_id"]) / "publish-payload.json"
    payload_path.unlink()

    def forbidden_run(cmd: list[str], input_json: str) -> str:
        del cmd, input_json
        raise AssertionError("dry-run called gh")

    monkeypatch.setattr(publish_module, "_run", forbidden_run)
    dry_run = runner.invoke(
        cli_module.app,
        ["publish", "--run", str(payload["run_id"]), "--out", str(out_root)],
    )

    commit = ResolvedTarget(
        kind="commit",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="c" * 40,
        changed_paths=[],
        diff="",
    )
    commit_run = RunStore(out_root / "commit").create(commit)
    commit_run.save_target(commit)
    non_pr = runner.invoke(
        cli_module.app,
        [
            "publish",
            "--run",
            commit_run.run_id,
            "--out",
            str(out_root / "commit"),
            "--execute",
        ],
    )

    assert dry_run.exit_code == 0, dry_run.stdout
    assert str(payload_path) in dry_run.stdout
    assert payload_path.is_file()
    assert json.loads(payload_path.read_text())["event"] == "COMMENT"
    assert non_pr.exit_code == 2
    assert "PR" in non_pr.stderr
