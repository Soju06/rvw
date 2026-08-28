from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner, Result

import rvw.cli as cli_module
import rvw.pipeline as pipeline_module
import rvw.publish as publish_module
from rvw.adjudicate import (
    AdjudicationAttempt,
    AdjudicationInfrastructureError,
    AdjudicationOutcome,
)
from rvw.discover import DiscoverResult
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import MergeResult
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode
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

    def __init__(self, **_kwargs: object) -> None:
        pass

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
    (
        "extra",
        "expected_discover",
        "expected_adjudicate",
        "expected_concurrency",
        "expected_deadline",
    ),
    [
        ([], 1, 3, 8, 600),
        (["--replicas", "2"], 2, 3, 8, 600),
        (["--adjudicate-replicas", "1"], 1, 1, 8, 600),
        (
            ["--replicas", "3", "--concurrency", "4", "--deadline", "1800"],
            3,
            3,
            4,
            1800,
        ),
    ],
)
def test_review_split_replica_defaults_and_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
    expected_discover: int,
    expected_adjudicate: int,
    expected_concurrency: int,
    expected_deadline: int,
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
    assert calls[0]["deadline_seconds"] == expected_deadline


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


def test_review_uses_tool_less_initial_and_agentic_expanded_runtime(
    monkeypatch: pytest.MonkeyPatch, registry_root: Path
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_execute_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _spec: pr_target())
    monkeypatch.setattr(cli_module, "execute_pipeline", fake_execute_pipeline)

    result = runner.invoke(
        cli_module.app,
        ["review", "--target", "HEAD", "--registry", str(registry_root)],
    )

    assert result.exit_code == 0, result.stdout
    assert cast(CodexRuntime, calls[0]["runtime"]).mode is CodexRuntimeMode.TOOL_LESS
    assert cast(CodexRuntime, calls[0]["adjudication_runtime"]).mode is CodexRuntimeMode.TOOL_LESS
    assert (
        cast(CodexRuntime, calls[0]["expanded_adjudication_runtime"]).mode
        is CodexRuntimeMode.AGENTIC
    )


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


async def test_shared_pipeline_propagates_split_replicas_concurrency_and_deadline(
    tmp_path: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each stage must receive ITS OWN replica count: distinct values prove
    execute_pipeline cannot forward one count to both stages."""

    stage_calls: list[tuple[str, int, int, int]] = []
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")

    async def fake_discover(**kwargs: object) -> DiscoverResult:
        assert kwargs["host_gate"] is gate
        replicas = kwargs["replicas"]
        concurrency = kwargs["concurrency"]
        deadline_seconds = kwargs["deadline_seconds"]
        assert isinstance(replicas, int)
        assert isinstance(concurrency, int)
        assert isinstance(deadline_seconds, int)
        stage_calls.append(("discover", replicas, concurrency, deadline_seconds))
        return DiscoverResult(lane_results={}, findings=[], coverage=[])

    discovery_runtime = cast(Runtime, FakeRuntime())
    expanded_runtime = cast(Runtime, FakeRuntime())

    async def fake_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        del merged
        assert kwargs["host_gate"] is gate
        assert kwargs["runtime"] is discovery_runtime
        assert kwargs["expanded_runtime"] is expanded_runtime
        replicas = kwargs["replicas"]
        concurrency = kwargs["concurrency"]
        deadline_seconds = kwargs["deadline_seconds"]
        assert isinstance(replicas, int)
        assert isinstance(concurrency, int)
        assert isinstance(deadline_seconds, int)
        stage_calls.append(("adjudicate", replicas, concurrency, deadline_seconds))
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
        runtime=discovery_runtime,
        adjudication_runtime=discovery_runtime,
        expanded_adjudication_runtime=expanded_runtime,
        adjudicator=fake_adjudicate,
        repo_dir=checkout,
        discover_replicas=2,
        adjudicate_replicas=5,
        concurrency=3,
        deadline_seconds=37,
        out_root=tmp_path / "runs",
        pause=False,
        dynamic_brief=None,
        host_gate=gate,
    )

    assert stage_calls == [("discover", 2, 3, 37), ("adjudicate", 5, 3, 37)]


def test_review_end_to_end_writes_all_stages_and_json_shape(
    tmp_path: Path, registry_root: Path, patched_pipeline: None
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result, payload = invoke_review(out_root, registry_root, "--repo-dir", str(repo_dir), "--json")

    assert result.exit_code == 0, result.stdout
    assert set(payload) == {
        "run_id",
        "report_path",
        "status",
        "failed_lanes",
        "verdict_counts",
        "coverage_totals",
        "error",
        "build",
    }
    run_dir = out_root / str(payload["run_id"])
    assert {path.name for path in run_dir.iterdir()} >= {
        "run.json",
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
    assert payload["status"] == "complete"
    assert payload["failed_lanes"] == []
    assert payload["error"] is None
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert set(summary) == {
        "schema_version",
        "run_id",
        "status",
        "failed_lanes",
        "coverage_totals",
        "error",
        "build",
    }
    assert payload["build"] == summary["build"]
    assert str(summary["build"]["build_id"]) in (run_dir / "report.md").read_text()
    assert "## 확정 발견 (CONFIRMED)" in (run_dir / "report.md").read_text()


def test_review_json_and_report_expose_degraded_failed_lane(
    tmp_path: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (registry_root / "layers.yaml").write_text(
        """layers:
  - id: base
    tier: base
    lanes: [test-lane, failed-lane]
""",
        encoding="utf-8",
    )
    (registry_root / "lanes" / "base" / "failed-lane.md").write_text(
        """---
lane: failed-lane
tier: base
cost: light
rules:
  - failed/rule
---

# failed lane
""",
        encoding="utf-8",
    )

    class PartialRuntime(FakeRuntime):
        async def execute(
            self,
            *,
            lane: Lane,
            prompt: str,
            run_dir: Path,
            deadline_seconds: int,
        ) -> RunResult[RuntimeLaneOutput]:
            if lane.id == "test-lane":
                return await super().execute(
                    lane=lane,
                    prompt=prompt,
                    run_dir=run_dir,
                    deadline_seconds=deadline_seconds,
                )
            return RunResult(
                lane_id=lane.id,
                replica=int(run_dir.name.removeprefix("r")),
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="missing",
                wall_seconds=0.01,
                artifact_dir=run_dir,
            )

    async def fake_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        del kwargs
        return AdjudicationOutcome(
            verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
            reasons={group.key: "verified" for group in merged.groups},
            evidence={group.key: "new" for group in merged.groups},
            replica_votes={group.key: [Verdict.CONFIRMED] for group in merged.groups},
            unresolved=[],
            coerced_rejections=0,
        )

    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _spec: pr_target())
    monkeypatch.setattr(cli_module, "CodexRuntime", PartialRuntime)
    monkeypatch.setattr(cli_module, "adjudicate", fake_adjudicate)
    out_root = tmp_path / "runs"
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result, payload = invoke_review(out_root, registry_root, "--repo-dir", str(repo_dir), "--json")

    assert result.exit_code == 0, result.stdout
    assert payload["status"] == "degraded"
    assert payload["coverage_totals"] == {"dispatched": 2, "valid": 1, "findings": 1}
    failed_lanes = cast(list[dict[str, object]], payload["failed_lanes"])
    assert [lane["lane_id"] for lane in failed_lanes] == ["failed-lane"]
    failures = cast(list[dict[str, object]], failed_lanes[0]["failures"])
    assert failures[0]["reason"] == "missing"
    run_dir = out_root / str(payload["run_id"])
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "status: `degraded`" in report
    assert "partial" in report
    assert "failed-lane" in report
    assert "fixture finding" in report


def test_review_with_every_lane_invalid_exits_failed(
    tmp_path: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidRuntime(FakeRuntime):
        async def execute(
            self,
            *,
            lane: Lane,
            prompt: str,
            run_dir: Path,
            deadline_seconds: int,
        ) -> RunResult[RuntimeLaneOutput]:
            del prompt, deadline_seconds
            return RunResult(
                lane_id=lane.id,
                replica=int(run_dir.name.removeprefix("r")),
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="schema-invalid",
                wall_seconds=0.01,
                artifact_dir=run_dir,
            )

    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _spec: pr_target())
    monkeypatch.setattr(cli_module, "CodexRuntime", InvalidRuntime)
    out_root = tmp_path / "runs"

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
            "--json",
        ],
    )

    assert result.exit_code == cli_module.EXIT_SYSTEM_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["coverage_totals"] == {"dispatched": 1, "valid": 0, "findings": 0}
    assert [lane["lane_id"] for lane in payload["failed_lanes"]] == ["test-lane"]


def test_review_adjudication_infrastructure_failure_persists_failed_partial_report(
    tmp_path: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        del merged, kwargs
        raise AdjudicationInfrastructureError(
            "initial",
            [
                AdjudicationAttempt(
                    wave="initial-retry",
                    replica=1,
                    reason="empty",
                    artifact_dir="/tmp/adjudicate/initial-retry/r1",
                    log_path="/tmp/adjudicate/initial-retry/r1/run.log",
                    log_bytes=0,
                    output_path="/tmp/adjudicate/initial-retry/r1/out.json",
                    output_bytes=0,
                )
            ],
        )

    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda _spec: pr_target())
    monkeypatch.setattr(cli_module, "CodexRuntime", FakeRuntime)
    monkeypatch.setattr(cli_module, "adjudicate", failed_adjudicate)
    out_root = tmp_path / "runs"
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result = runner.invoke(
        cli_module.app,
        [
            "review",
            "--target",
            "42",
            "--registry",
            str(registry_root),
            "--repo-dir",
            str(repo_dir),
            "--out",
            str(out_root),
            "--json",
        ],
    )

    assert result.exit_code == cli_module.EXIT_SYSTEM_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["error"]["reason"] == "no-valid-output"
    assert payload["error"]["attempts"][0]["reason"] == "empty"
    assert payload["verdict_counts"] == {
        "CONFIRMED": 0,
        "REJECTED": 0,
        "UNCERTAIN": 0,
    }
    run_dir = out_root / str(payload["run_id"])
    assert not (run_dir / "outcome.json").exists()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "status: `failed`" in report
    assert "no-valid-output" in report
    assert "fixture finding" in report


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


def test_new_run_emits_stale_install_warning_once(
    tmp_path: Path,
    registry_root: Path,
    patched_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del patched_pipeline
    calls = 0

    def warning() -> str:
        nonlocal calls
        calls += 1
        return "warning: reinstall fixture"

    monkeypatch.setattr(pipeline_module, "stale_install_warning", warning)
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result, _ = invoke_review(tmp_path / "runs", registry_root, "--repo-dir", str(repo_dir))

    assert result.exit_code == 0, result.stdout
    assert calls == 1
    assert result.stderr.count("warning: reinstall fixture") == 1


def test_adjudicate_run_reuses_persisted_artifacts_and_rewrites_outcome_report(
    tmp_path: Path,
    registry_root: Path,
    patched_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del patched_pipeline
    out_root = tmp_path / "runs"
    review_result, payload = invoke_review(out_root, registry_root, "--json")
    assert review_result.exit_code == 0
    run_dir = out_root / str(payload["run_id"])
    discover_before = (run_dir / "discover.json").read_bytes()
    report_before = (run_dir / "report.md").read_bytes()
    build_before = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["build"]
    calls: list[dict[str, object]] = []
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")

    async def fresh_adjudicate(merged: MergeResult, **kwargs: object) -> AdjudicationOutcome:
        calls.append(kwargs)
        return AdjudicationOutcome(
            verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
            reasons={group.key: "fresh reason" for group in merged.groups},
            evidence={group.key: "fresh evidence" for group in merged.groups},
            replica_votes={group.key: [Verdict.CONFIRMED] for group in merged.groups},
            unresolved=[],
            coerced_rejections=0,
        )

    monkeypatch.setattr(cli_module, "adjudicate", fresh_adjudicate)
    monkeypatch.setattr(cli_module, "_command_host_gate", lambda: gate)
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result = runner.invoke(
        cli_module.app,
        [
            "adjudicate",
            "--run",
            str(payload["run_id"]),
            "--repo-dir",
            str(repo_dir),
            "--out",
            str(out_root),
            "--replicas",
            "1",
            "--concurrency",
            "2",
            "--deadline",
            "37",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert calls[0]["replicas"] == 1
    assert calls[0]["concurrency"] == 2
    assert calls[0]["deadline_seconds"] == 37
    assert calls[0]["host_gate"] is gate
    assert cast(Path, calls[0]["repo_dir"]) == repo_dir
    assert "readjudicate-" in str(calls[0]["out_root"])
    assert (run_dir / "discover.json").read_bytes() == discover_before
    assert (run_dir / "outcome.json").is_file()
    assert (run_dir / "report.md").read_bytes() != report_before
    assert "## 확정 발견 (CONFIRMED)" in (run_dir / "report.md").read_text(encoding="utf-8")
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["build"] == build_before


def test_adjudicate_run_names_missing_merge_without_runtime_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunStore(tmp_path).create(pr_target())
    run.save_target(pr_target())
    run.save_discover(DiscoverResult(lane_results={}, findings=[], coverage=[]))
    called = False

    async def forbidden_adjudicate(*args: object, **kwargs: object) -> AdjudicationOutcome:
        del args, kwargs
        nonlocal called
        called = True
        raise AssertionError("adjudicator must not run without merge.json")

    monkeypatch.setattr(cli_module, "adjudicate", forbidden_adjudicate)
    monkeypatch.setattr(cli_module, "_command_host_gate", lambda: None)
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    result = runner.invoke(
        cli_module.app,
        [
            "adjudicate",
            "--run",
            run.run_id,
            "--repo-dir",
            str(repo_dir),
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == cli_module.EXIT_NOT_FOUND
    assert "merge.json" in result.stderr
    assert called is False


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
