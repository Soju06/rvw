from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cli_phase5 import fixture_artifacts, policy_file, target
from test_cli_review import FakeRuntime
from typer.testing import CliRunner

import rvw.cli as cli
import rvw.pipeline as pipeline
from rvw.adjudicate import AdjudicationOutcome
from rvw.checkout import CheckoutVerificationError
from rvw.discover import DiscoverResult
from rvw.lane import Lane
from rvw.merge import MergeResult
from rvw.pipeline import PipelineArtifacts
from rvw.registry import Registry
from rvw.schema import Tier, Verdict
from rvw.summary import ExecutionSummary, ProcessResult

runner = CliRunner()


@pytest.fixture
def offline_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PipelineArtifacts:
    """Keep real stage persistence/merging, replace only external execution boundaries."""
    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setenv("RVW_HOST_CONCURRENCY", "0")
    monkeypatch.setenv("RVW_CODEX_SANDBOX", "read-only")
    monkeypatch.setattr(cli, "DEFAULT_RUN_ROOT", tmp_path / "contract")
    monkeypatch.setattr(cli, "DEFAULT_AUTO_POLICY", tmp_path / "absent-external.yaml")
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: target())
    monkeypatch.setattr(cli, "provision_checkout", lambda **_: checkout)
    monkeypatch.setattr(cli, "CodexRuntime", FakeRuntime)
    monkeypatch.setattr(pipeline, "verify_checkout", lambda *_, **__: None)
    monkeypatch.setattr(cli, "load_effective_registry", lambda *_, **__: Registry(layers=[]))
    lanes = [
        Lane(
            lane=lane_id,
            tier=Tier.DYNAMIC if lane_id.startswith("dynamic/") else Tier.BASE,
            rules=["fixture/rule"],
            prompt_body="Offline fixture lane.",
        )
        for lane_id in sorted({finding.lane_id for finding in artifacts.discovered.findings})
    ]
    monkeypatch.setattr(cli, "_load_active_lanes", lambda *_, **__: lanes)

    async def discover(**_: object) -> DiscoverResult:
        return artifacts.discovered

    async def adjudicate(_merged: MergeResult, **_: object) -> AdjudicationOutcome:
        assert artifacts.outcome is not None
        return artifacts.outcome

    def forbid_publish(**_: object) -> None:
        pytest.fail("offline contract unexpectedly attempted GitHub publication")

    monkeypatch.setattr(pipeline, "discover", discover)
    monkeypatch.setattr(cli, "adjudicate", adjudicate)
    monkeypatch.setattr(cli, "publish_review", forbid_publish)
    return artifacts


def invocation(command: str, out: Path, policy: Path | str) -> list[str]:
    return [
        command,
        "--target",
        "https://github.com/owner/repo/pull/42",
        "--out",
        str(out),
        "--policy",
        str(policy),
        *(["--publish", "none"] if command == "run" else ["--no-publish"]),
        "--json",
    ]


def assert_contract(out: Path, expected_exit: int) -> ProcessResult:
    process = ProcessResult.model_validate_json((out / "process.json").read_text())
    assert process.exit_code == expected_exit
    assert process.command[:2] == ["rvw", "run"]
    assert process.status == {0: "pass", 1: "block", 2: "invalid", 3: "infra_failed"}[expected_exit]
    actual = {
        path.relative_to(out).as_posix(): path.stat().st_size
        for path in out.rglob("*")
        if path.is_file()
    }
    assert {item.path: item.size_bytes for item in process.artifacts} == actual
    assert {"process.json", "summary.json", "run.log", "environment.txt"} <= actual.keys()
    ExecutionSummary.model_validate_json((out / "summary.json").read_text())
    return process


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize(
    "result_kind,expected_exit", [("pass", 0), ("block", 1), ("invalid", 2), ("infra", 3)]
)
def test_run_and_auto_exit_matrix_with_real_stage_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_pipeline: PipelineArtifacts,
    command: str,
    result_kind: str,
    expected_exit: int,
) -> None:
    policy = policy_file(tmp_path, "none")
    if result_kind == "pass":

        async def reject_all(merged: MergeResult, **_: object) -> AdjudicationOutcome:
            return AdjudicationOutcome(
                verdicts={group.key: Verdict.REJECTED for group in merged.groups},
                reasons={group.key: "fixture rejected" for group in merged.groups},
                evidence={group.key: "fixture source" for group in merged.groups},
                replica_votes={group.key: [Verdict.REJECTED] * 3 for group in merged.groups},
                unresolved=[],
                coerced_rejections=0,
            )

        monkeypatch.setattr(cli, "adjudicate", reject_all)
    elif result_kind == "invalid":
        policy.write_text("publish_state: approve\n", encoding="utf-8")
    elif result_kind == "infra":

        async def runtime_failed(**_: object) -> DiscoverResult:
            raise RuntimeError("fixture runtime unavailable")

        monkeypatch.setattr(pipeline, "discover", runtime_failed)

    out = tmp_path / "result"
    result = runner.invoke(cli.app, invocation(command, out, policy))
    assert result.exit_code == expected_exit, result.output
    process = assert_contract(out, expected_exit)
    assert json.loads(result.stdout) == process.model_dump(mode="json")
    if expected_exit in {0, 1}:
        assert process.failure is None
        summary = ExecutionSummary.model_validate_json((out / "summary.json").read_text())
        assert summary.lanes.valid == 1
        assert summary.lanes.dispatched == 1
        assert sum(summary.findings.model_dump().values()) == len(offline_pipeline.merged.groups)
        assert bool(summary.blockers) == (expected_exit == 1)
        assert {"discover.json", "merge.json", "outcome.json", "report.md"} <= {
            item.path for item in process.artifacts
        }
    else:
        assert process.failure is not None
        assert process.failure.code == ("invalid_policy" if expected_exit == 2 else "review_failed")


@pytest.mark.parametrize("command", ["run", "auto"])
def test_checkout_exception_is_infrastructure_with_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_pipeline: PipelineArtifacts,
    command: str,
) -> None:
    del offline_pipeline

    def broken_checkout(**_: object) -> Path:
        raise CheckoutVerificationError("head-mismatch", "fixture detached checkout mismatch")

    monkeypatch.setattr(cli, "provision_checkout", broken_checkout)
    out = tmp_path / "result"
    result = runner.invoke(cli.app, invocation(command, out, policy_file(tmp_path, "none")))
    assert result.exit_code == 3, result.output
    process = assert_contract(out, 3)
    assert process.failure is not None
    assert process.failure.code == "checkout_failed"
    assert "head-mismatch" in process.failure.detail
    assert (out / "target.json").is_file()
    assert not (out / "discover.json").exists()


@pytest.mark.parametrize("command", ["run", "auto"])
def test_unexpected_adjudication_exception_retains_partial_stages_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_pipeline: PipelineArtifacts,
    command: str,
) -> None:
    async def broken_adjudication(_merged: MergeResult, **_: object) -> AdjudicationOutcome:
        raise RuntimeError("fixture unexpected adjudication failure")

    monkeypatch.setattr(cli, "adjudicate", broken_adjudication)
    out = tmp_path / "result"
    result = runner.invoke(cli.app, invocation(command, out, policy_file(tmp_path, "none")))
    assert result.exit_code == 3, result.output
    process = assert_contract(out, 3)
    assert process.failure is not None
    assert "fixture unexpected adjudication failure" in process.failure.detail
    assert {"discover.json", "merge.json"} <= {item.path for item in process.artifacts}
    assert not (out / "outcome.json").exists()
    summary = ExecutionSummary.model_validate_json((out / "summary.json").read_text())
    assert summary.lanes.valid == 1
    assert summary.lanes.dispatched == 1
    assert sum(summary.findings.model_dump().values()) == len(offline_pipeline.merged.groups)


@pytest.mark.parametrize("command", ["run", "auto"])
@pytest.mark.parametrize("invalid_kind", ["target", "missing_policy"])
def test_invalid_inputs_without_checkout_fail_before_provisioning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_pipeline: PipelineArtifacts,
    command: str,
    invalid_kind: str,
) -> None:
    del offline_pipeline
    checkout_calls: list[object] = []

    def forbid_checkout(**kwargs: object) -> Path:
        checkout_calls.append(kwargs)
        raise AssertionError("invalid input reached checkout provisioning")

    monkeypatch.setattr(cli, "provision_checkout", forbid_checkout)
    selected_policy = tmp_path / "missing.yaml"
    if invalid_kind == "target":
        selected_policy = policy_file(tmp_path, "none")

        def invalid_target(_: str):
            raise ValueError("unsupported target specification: 'bad-target'")

        monkeypatch.setattr(cli, "_resolve_cli_target", invalid_target)
    out = tmp_path / "result"
    args = invocation(command, out, selected_policy)
    if invalid_kind == "target":
        args[args.index("--target") + 1] = "bad-target"
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    assert checkout_calls == []
    process = assert_contract(out, 2)
    assert process.failure is not None
    assert process.failure.code == (
        "invalid_target" if invalid_kind == "target" else "policy_not_found"
    )
    assert not (out / "discover.json").exists()


@pytest.mark.parametrize("command", ["run", "auto"])
def test_package_fallback_provenance_reaches_process_contract(
    tmp_path: Path,
    offline_pipeline: PipelineArtifacts,
    command: str,
) -> None:
    del offline_pipeline
    out = tmp_path / "result"
    result = runner.invoke(cli.app, invocation(command, out, "auto"))
    assert result.exit_code == 1, result.output
    process = assert_contract(out, 1)
    assert process.effective_policy.source == "package"
    assert process.effective_policy.path == "rvw:resources/policies/auto-default.yaml"


@pytest.mark.parametrize("command", ["run", "auto"])
def test_zero_number_pr_url_is_invalid_and_retains_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_pipeline: PipelineArtifacts,
    command: str,
) -> None:
    del offline_pipeline

    def invalid_target(_: str):
        raise ValueError("pull-request number must be positive")

    monkeypatch.setattr(cli, "_resolve_cli_target", invalid_target)
    out = tmp_path / "result"
    args = invocation(command, out, policy_file(tmp_path, "none"))
    args[args.index("--target") + 1] = "https://github.com/owner/repo/pull/0"
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    process = assert_contract(out, 2)
    assert process.failure is not None
    assert process.failure.code == "invalid_target"
