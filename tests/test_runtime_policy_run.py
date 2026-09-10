"""The resolved Codex policy must reach every runtime artifact of a full offline run.

Discovery (initial, ordinary retry, coverage redispatch) and adjudication (three initial
replicas) each write ``usage.json`` through the real ``CodexRuntime`` telemetry path; the
runtime subclass below replaces only the ``codex exec`` spawn with scripted results.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from test_cli_phase5 import policy_file
from typer.testing import CliRunner

import rvw.cli as cli
import rvw.pipeline as pipeline
from rvw.lane import Lane
from rvw.presentation import PresentationConfig
from rvw.registry import EffectiveRegistry, LaneSource
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, RunUsage, RunUsageStatus
from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode
from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier
from rvw.target import ResolvedTarget

runner = CliRunner()

# ``a.py`` gains one line inside a three-line hunk; line 2 is the added line.
FIXTURE_DIFF = (
    "diff --git a/a.py b/a.py\n"
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+VALUE = 1\n"
    " print(os.name)\n"
)
FINDING_LINE = 2
# Every wave the scripted run must drive, relative to the run directory.
EXPECTED_USAGE_DIRS = frozenset(
    {
        "discover-runtime/fixture-lane/r1",
        "discover-runtime/fixture-lane/retry/r1",
        "discover-runtime/coverage-redispatch/fixture-lane/r1",
        "adjudicate-runtime/initial/r1",
        "adjudicate-runtime/initial/r2",
        "adjudicate-runtime/initial/r3",
        "synthesis-runtime/initial/r1",
    }
)


def fixture_target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["a.py"],
        diff=FIXTURE_DIFF,
        pr_number=42,
    )


def fixture_lane() -> Lane:
    return Lane(
        lane="fixture-lane",
        tier=Tier.BASE,
        rules=["fixture/rule"],
        prompt_body="Offline fixture lane.",
    )


@dataclass
class OfflineRun:
    checkout: Path
    policy: Path
    executions: list[Path] = field(default_factory=list)
    raw_executions: list[Path] = field(default_factory=list)


def recording_runtime_class(record: OfflineRun) -> type[CodexRuntime]:
    class RecordingCodexRuntime(CodexRuntime):
        """Scripted lane and adjudication results written through the real usage path.

        The first lane execution is INVALID so the dispatcher runs its ordinary retry; every
        later lane execution is VALID with no coverage receipts so discovery runs the coverage
        redispatch (the lane is not dead by timeout). Adjudication confirms every candidate so
        no expanded pass is needed.
        """

        async def execute(
            self,
            *,
            lane: Lane,
            prompt: str,
            run_dir: Path,
            deadline_seconds: int,
            workdir: Path | None = None,
        ) -> RunResult[RuntimeLaneOutput]:
            del prompt, deadline_seconds, workdir
            started = time.perf_counter()
            run_dir.mkdir(parents=True, exist_ok=True)
            log_path = run_dir / "run.log"
            replica = int(run_dir.name.removeprefix("r"))
            first_attempt = not record.executions
            record.executions.append(run_dir)
            if first_attempt:
                usage = self._usage(
                    status=RunUsageStatus.INVALID, started=started, log_path=log_path
                )
                self._save_usage(run_dir, usage)
                return RunResult(
                    lane_id=lane.id,
                    replica=replica,
                    status=RunStatus.INVALID,
                    output=None,
                    invalid_reason="scripted-invalid",
                    wall_seconds=usage.wall_seconds,
                    artifact_dir=run_dir,
                    diagnostic=RunDiagnostic(exit_code=1, detail="scripted invalid attempt"),
                    usage=usage,
                )
            usage = self._usage(status=RunUsageStatus.COMPLETED, started=started, log_path=log_path)
            self._save_usage(run_dir, usage)
            return RunResult(
                lane_id=lane.id,
                replica=replica,
                status=RunStatus.VALID,
                output=RuntimeLaneOutput(
                    verdict="findings",
                    covered=[],
                    findings=[
                        RuntimeFinding(
                            rule_id="fixture/rule",
                            file="a.py",
                            line=FINDING_LINE,
                            severity=Severity.WARNING,
                            body="fixture finding",
                        )
                    ],
                ),
                invalid_reason=None,
                wall_seconds=usage.wall_seconds,
                artifact_dir=run_dir,
                usage=usage,
            )

        async def execute_raw(
            self,
            *,
            schema: dict[str, Any],
            prompt: str,
            run_dir: Path,
            deadline_seconds: int,
            workdir: Path | None = None,
            validate: Callable[[object], BaseModel],
        ) -> RunResult[BaseModel]:
            del prompt, deadline_seconds, workdir
            started = time.perf_counter()
            run_dir.mkdir(parents=True, exist_ok=True)
            record.raw_executions.append(run_dir)
            if "overview" in schema["properties"]:
                assert self.mode is CodexRuntimeMode.TOOL_LESS
                retained = json.loads((run_dir.parents[2] / "merge.json").read_text())
                output = validate(
                    {
                        "overview": "This change adjusts the configured value. The check needs attention.",
                        "first_action": "Address the reported check before merging.",
                        "findings": [
                            {
                                "key": group["key"],
                                "title": "The changed value needs a check.",
                                "what": "The check in `a.py` reports a fixture finding.",
                                "consequence": "The affected check remains unresolved.",
                                "fix": "Update the affected check.",
                            }
                            for group in retained["groups"]
                        ],
                    }
                )
            else:
                group_keys = schema["properties"]["items"]["items"]["properties"]["group_key"][
                    "enum"
                ]
                output = validate(
                    {
                        "items": [
                            {
                                "group_key": key,
                                "verdict": "CONFIRMED",
                                "reason": "verified",
                                "evidence": "source quote",
                            }
                            for key in group_keys
                        ]
                    }
                )
            usage = self._usage(
                status=RunUsageStatus.COMPLETED, started=started, log_path=run_dir / "run.log"
            )
            self._save_usage(run_dir, usage)
            return RunResult(
                lane_id=run_dir.parent.name,
                replica=int(run_dir.name.removeprefix("r")),
                status=RunStatus.VALID,
                output=output,
                invalid_reason=None,
                wall_seconds=usage.wall_seconds,
                artifact_dir=run_dir,
                usage=usage,
            )

    return RecordingCodexRuntime


@pytest.fixture
def offline_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> OfflineRun:
    """A full ``rvw run`` with real discovery, dispatch, merge, adjudication, and persistence."""

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "a.py").write_text("import os\nVALUE = 1\nprint(os.name)\n", encoding="utf-8")
    record = OfflineRun(checkout=checkout, policy=policy_file(tmp_path, "none"))
    for name in ("RVW_CODEX_MODEL", "RVW_CODEX_REASONING_EFFORT", "RVW_NO_OUTPUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RVW_HOST_CONCURRENCY", "0")
    monkeypatch.setenv("RVW_CODEX_SANDBOX", "read-only")
    monkeypatch.setattr(cli, "DEFAULT_RUN_ROOT", tmp_path / "contract")
    monkeypatch.setattr(cli, "DEFAULT_AUTO_POLICY", tmp_path / "absent-external.yaml")
    monkeypatch.setattr(cli, "load_repo_presentation", lambda *_, **__: PresentationConfig())
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _spec: fixture_target())
    monkeypatch.setattr(pipeline, "verify_checkout", lambda *_, **__: None)

    def forbid_checkout(**_: object) -> Path:
        pytest.fail("--repo-dir was supplied; the run must not provision a checkout")

    def forbid_publish(**_: object) -> None:
        pytest.fail("publish_state none must not reach GitHub publication")

    monkeypatch.setattr(cli, "provision_checkout", forbid_checkout)
    monkeypatch.setattr(cli, "publish_review", forbid_publish)
    lane = fixture_lane()
    registry = EffectiveRegistry(
        [LaneSource(lane=lane, path=tmp_path / "fixture-lane.md", source="package")]
    )
    monkeypatch.setattr(cli, "load_effective_registry", lambda *_, **__: registry)
    monkeypatch.setattr(cli, "CodexRuntime", recording_runtime_class(record))
    return record


def run_invocation(record: OfflineRun, out: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--target",
        "https://github.com/owner/repo/pull/42",
        "--repo-dir",
        str(record.checkout),
        "--out",
        str(out),
        "--policy",
        str(record.policy),
        "--publish",
        "none",
        *extra,
        "--json",
    ]


@pytest.mark.parametrize(
    "environment,extra,expected_model,expected_effort",
    [
        ({}, [], "gpt-6-astra", "high"),
        ({"RVW_CODEX_REASONING_EFFORT": "medium"}, [], "gpt-6-astra", "medium"),
        (
            {"RVW_CODEX_REASONING_EFFORT": "medium"},
            ["--model", "gpt-5.6-sol"],
            "gpt-5.6-sol",
            "medium",
        ),
    ],
)
def test_resolved_policy_reaches_every_usage_artifact_of_a_full_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    offline_run: OfflineRun,
    environment: dict[str, str],
    extra: list[str],
    expected_model: str,
    expected_effort: str,
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    out = tmp_path / "result"

    result = runner.invoke(cli.app, run_invocation(offline_run, out, *extra))

    assert result.exit_code in {0, 1}, result.output
    process = json.loads((out / "process.json").read_text(encoding="utf-8"))
    assert process["status"] in {"pass", "block"}
    assert process["failure"] is None
    assert json.loads(result.stdout) == process

    # The scripted invalid first attempt forced the ordinary retry, the empty receipts forced
    # the coverage redispatch, and the confirmed adjudication needed no expanded pass.
    usage_paths = sorted(out.rglob("usage.json"))
    usage_dirs = {path.parent.relative_to(out).as_posix() for path in usage_paths}
    assert usage_dirs >= EXPECTED_USAGE_DIRS, usage_dirs
    assert not any(directory.startswith("adjudicate-runtime/expanded") for directory in usage_dirs)
    discover = json.loads((out / "discover.json").read_text(encoding="utf-8"))
    [lane_coverage] = discover["coverage"]
    assert lane_coverage["coverage_redispatched"] is True
    assert [attempt["wave"] for attempt in lane_coverage["runs"][0]["attempts"]] == [
        "initial",
        "retry",
    ]
    assert [attempt["wave"] for attempt in lane_coverage["redispatch"]] == ["coverage_redispatch"]
    assert len(offline_run.raw_executions) == 4
    synthesis = json.loads((out / "synthesis.json").read_text(encoding="utf-8"))
    assert synthesis["overview"].startswith("This change")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["synthesis"]["status"] == "ok"
    assert summary["synthesis"]["model"] == expected_model
    assert summary["synthesis"]["reasoning_effort"] == expected_effort

    for path in usage_paths:
        usage = RunUsage.model_validate_json(path.read_text(encoding="utf-8"))
        assert usage.model == expected_model, path
        assert usage.reasoning_effort == expected_effort, path
        assert usage.reasoning_summary == "detailed", path

    assert process["runtime"]["model"] == expected_model
    assert process["runtime"]["reasoning_effort"] == expected_effort
    command = process["command"]
    assert command[command.index("--model") + 1] == expected_model
    assert command[command.index("--reasoning-effort") + 1] == expected_effort
    environment_lines = (out / "environment.txt").read_text(encoding="utf-8").splitlines()
    assert f"model={expected_model}" in environment_lines
    assert f"reasoning_effort={expected_effort}" in environment_lines
    listed = {artifact["path"] for artifact in process["artifacts"]}
    assert {f"{directory}/usage.json" for directory in EXPECTED_USAGE_DIRS} <= listed


def test_explicit_effort_beats_the_environment_in_every_usage_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, offline_run: OfflineRun
) -> None:
    monkeypatch.setenv("RVW_CODEX_MODEL", "env-model")
    monkeypatch.setenv("RVW_CODEX_REASONING_EFFORT", "low")
    out = tmp_path / "result"

    result = runner.invoke(
        cli.app,
        run_invocation(offline_run, out, "--model", "gpt-6-astra", "--reasoning-effort", "high"),
    )

    assert result.exit_code in {0, 1}, result.output
    usage_paths = sorted(out.rglob("usage.json"))
    assert {path.parent.relative_to(out).as_posix() for path in usage_paths} >= EXPECTED_USAGE_DIRS
    for path in usage_paths:
        usage = RunUsage.model_validate_json(path.read_text(encoding="utf-8"))
        assert (usage.model, usage.reasoning_effort) == ("gpt-6-astra", "high"), path
    process = json.loads((out / "process.json").read_text(encoding="utf-8"))
    assert process["runtime"]["model"] == "gpt-6-astra"
    assert process["runtime"]["reasoning_effort"] == "high"
