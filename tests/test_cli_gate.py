from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage, RunCoverage
from rvw.gate import GatePlan, PullRequestState, load_gate_plan, save_gate_plan
from rvw.merge import merge
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunStore
from rvw.target import ResolvedTarget

runner = CliRunner()


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py"],
        diff="diff --git a/src/a.py b/src/a.py\n",
        pr_number=42,
    )


def current_state(*, head_sha: str = "b" * 40) -> PullRequestState:
    return PullRequestState(
        base_sha="a" * 40,
        head_sha=head_sha,
        state="open",
        merged=False,
    )


def prepared_artifacts(
    out_root: Path,
    *,
    actionable: bool = False,
    replicas: int = 1,
    valid: int | None = None,
    blocker: bool = False,
) -> cli_module._PipelineArtifacts:
    valid = replicas if valid is None else valid
    run = RunStore(out_root).create(target())
    run.save_target(target())
    findings: list[EnrichedFinding] = []
    if actionable:
        findings.append(
            EnrichedFinding(
                rule_id="rule/actionable",
                file="src/a.py",
                hunk_id="src/a.py@@-1+1@@",
                line=1,
                severity=Severity.BLOCKER if blocker else Severity.WARNING,
                body="actionable",
                anchorable=True,
                lane_id="lane-a",
                replica=1,
            )
        )
    discovered = DiscoverResult(
        lane_results={},
        findings=findings,
        coverage=[
            LaneCoverage(
                lane_id="lane-a",
                dispatched=replicas,
                valid=valid,
                findings=len(findings),
                runs=[
                    RunCoverage(
                        replica=replica,
                        chunk=1,
                        valid=replica <= valid,
                        findings=len(findings) if replica == 1 else 0,
                        invalid_reason=None if replica <= valid else "scripted_invalid",
                    )
                    for replica in range(1, replicas + 1)
                ],
            )
        ],
        budget=None,
    )
    run.save_discover(discovered)
    merged = merge(findings, lane_tiers={"lane-a": Tier.BASE})
    run.save_merge(merged)
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
        reasons={group.key: "confirmed" for group in merged.groups},
        evidence={group.key: "evidence" for group in merged.groups},
        replica_votes={group.key: [Verdict.CONFIRMED] * replicas for group in merged.groups},
        unresolved=[],
        coerced_rejections=0,
    )
    run.save_outcome(outcome)
    report = "# ordinary report\n"
    run.save_report(report)
    return cli_module._PipelineArtifacts(
        run=run,
        target=target(),
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report,
        report_path=run.dir / "report.md",
    )


def patch_target_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: cli_module._PipelineArtifacts,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda spec: target())
    monkeypatch.setattr(
        cli_module,
        "_gate_plan",
        lambda registry_root, resolved, replicas: GatePlan(
            schema_version=1, lane_ids=["lane-a"], replicas=replicas, chunk_count=1
        ),
    )

    def fake_checkout(*, repo: str, pr_number: int, head_sha: str, destination: Path) -> Path:
        del repo, pr_number, head_sha
        destination.mkdir()
        return destination

    async def fake_execute(**kwargs: object) -> cli_module._PipelineArtifacts:
        calls.append(kwargs)
        return artifacts

    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_execute)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())
    return calls


def test_gate_target_executes_review_once_and_writes_dry_run_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    calls = patch_target_dependencies(monkeypatch, artifacts)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 1
    assert calls[0]["replicas"] == 1
    assert calls[0]["resolved_target"] == target()
    repo_dir = calls[0]["repo_dir"]
    assert isinstance(repo_dir, Path)
    assert repo_dir.name == "checkout"
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS"
    assert (artifacts.run.dir / "gate-plan.json").is_file()
    assert load_gate_plan(artifacts.run.dir).replicas == 1
    assert (artifacts.run.dir / "gate-verdict.json").is_file()
    publish_payload = json.loads(
        (artifacts.run.dir / "publish-payload.json").read_text(encoding="utf-8")
    )
    assert publish_payload["event"] == "COMMENT"
    assert "rvw gate — PASS" in publish_payload["body"]


def test_gate_preserves_explicit_replica_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, replicas=3)
    calls = patch_target_dependencies(monkeypatch, artifacts)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--replicas", "3", "--out", str(out_root)],
    )

    assert result.exit_code == 0, result.stdout
    assert calls[0]["replicas"] == 3
    assert load_gate_plan(artifacts.run.dir).replicas == 3


@pytest.mark.parametrize(
    "args",
    [
        ["gate"],
        ["gate", "--target", "42", "--run", "run-1"],
    ],
)
def test_gate_requires_exactly_one_target_or_run(args: list[str]) -> None:
    result = runner.invoke(cli_module.app, args)

    assert result.exit_code == 2
    assert "exactly one" in result.stderr


def test_gate_invalid_target_is_user_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def invalid_target(spec: str) -> ResolvedTarget:
        raise ValueError(f"unsupported target: {spec}")

    monkeypatch.setattr(cli_module, "_resolve_cli_target", invalid_target)
    result = runner.invoke(cli_module.app, ["gate", "--target", "invalid"])

    assert result.exit_code == 2
    assert "unsupported target" in result.stderr


def test_gate_checkout_failure_is_operational_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda spec: target())
    monkeypatch.setattr(
        cli_module,
        "_gate_plan",
        lambda registry_root, resolved, replicas: GatePlan(
            schema_version=1, lane_ids=["lane-a"], replicas=replicas, chunk_count=1
        ),
    )

    def failed_checkout(**kwargs: object) -> Path:
        raise OSError(f"clone failed: {kwargs['repo']}")

    monkeypatch.setattr(cli_module, "provision_checkout", failed_checkout)
    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(tmp_path / "runs")],
    )

    assert result.exit_code == 3
    assert "clone failed" in result.stderr


def test_gate_without_dispositions_writes_template_and_does_not_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True)
    calls = patch_target_dependencies(monkeypatch, artifacts)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )

    assert result.exit_code == 1
    assert len(calls) == 1
    assert "--run" in result.stdout
    assert (artifacts.run.dir / "gate-dispositions.yaml").is_file()
    assert not (artifacts.run.dir / "publish-payload.json").exists()


def test_gate_resume_uses_artifacts_without_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True, replicas=3)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=3, chunk_count=1),
    )
    finding_id = artifacts.merged.groups[0].key
    disposition_path = tmp_path / "dispositions.yaml"
    disposition_path.write_text(
        "schema_version: 1\ndispositions:\n"
        f"  - finding_id: {finding_id}\n"
        "    decision: accepted\n"
        "    reason: reviewed by owner\n",
        encoding="utf-8",
    )

    async def forbidden_execute(**kwargs: object) -> None:
        raise AssertionError(f"resume executed review: {kwargs}")

    monkeypatch.setattr(cli_module, "_execute_pipeline", forbidden_execute)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())
    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            artifacts.run.run_id,
            "--dispositions",
            str(disposition_path),
            "--out",
            str(out_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["run_id"] == artifacts.run.run_id
    assert (artifacts.run.dir / "publish-payload.json").is_file()


def test_gate_stale_resume_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, replicas=3)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=3, chunk_count=1),
    )
    monkeypatch.setattr(
        cli_module,
        "query_pull_request",
        lambda repo, number: current_state(head_sha="c" * 40),
    )

    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root)],
    )

    assert result.exit_code == 1
    assert "stale" in result.stderr
    verdict = json.loads((artifacts.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "BLOCK"
    assert any("stale" in failure for failure in verdict["failures"])
    assert not (artifacts.run.dir / "publish-payload.json").exists()


def test_gate_invalid_coverage_cannot_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, valid=0)
    patch_target_dependencies(monkeypatch, artifacts)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )

    assert result.exit_code == 1
    assert "valid" in result.stderr
    assert not (artifacts.run.dir / "publish-payload.json").exists()


def test_gate_accepted_blocker_verifies_admin_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True, blocker=True)
    calls = patch_target_dependencies(monkeypatch, artifacts)
    finding_id = artifacts.merged.groups[0].key
    disposition_path = tmp_path / "dispositions.yaml"
    disposition_path.write_text(
        "schema_version: 1\ndispositions:\n"
        f"  - finding_id: {finding_id}\n"
        "    decision: accepted\n"
        "    reason: owner accepts release risk\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "github_actor_permission",
        lambda repo: ("repo-owner", "admin"),
    )

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--dispositions",
            str(disposition_path),
            "--out",
            str(out_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 1
    verdict = json.loads((artifacts.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["actor"] == "repo-owner"
    assert (
        json.loads((artifacts.run.dir / "publish-payload.json").read_text(encoding="utf-8"))[
            "event"
        ]
        == "COMMENT"
    )
