from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Literal

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage, RunCoverage
from rvw.gate import (
    DispositionDecision,
    GateAnchor,
    GateFinding,
    GatePlan,
    GateVerdict,
    PullRequestState,
    load_gate_plan,
    render_gate_verdict,
    save_gate_plan,
    save_gate_verdict,
)
from rvw.merge import merge
from rvw.publish import PublishResult
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunHandle, RunStore
from rvw.target import ResolvedTarget

runner = CliRunner()

HUNK_TEXT = "@@ -1 +1 @@\n-old\n+new\n"
HUNK_DIFF = f"diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n{HUNK_TEXT}"
HUNK_SHA256 = hashlib.sha256(HUNK_TEXT.encode()).hexdigest()
BODY_SHA256 = hashlib.sha256(hashlib.sha256(b"actionable").digest()).hexdigest()


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py"],
        diff=HUNK_DIFF,
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
                hunk_id="src/a.py@@-1,1+1,1@@",
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


def inherited_source(
    out_root: Path,
    current: cli_module._PipelineArtifacts,
    *,
    repo: str = "owner/repo",
    pr_number: int = 42,
    write_verdict: bool = True,
    verdict: Literal["PASS", "BLOCK"] = "PASS",
) -> RunHandle:
    run = RunHandle(run_id="source-run", dir=out_root / "source-run")
    run.dir.mkdir(parents=True)
    source_target = target().model_copy(update={"repo": repo, "pr_number": pr_number})
    run.save_target(source_target)
    if write_verdict:
        group = current.merged.groups[0]
        save_gate_verdict(
            run.dir,
            GateVerdict(
                run_id=run.run_id,
                repo=repo,
                pr_number=pr_number,
                anchor=GateAnchor(base_sha="c" * 40, head_sha="d" * 40),
                counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
                coverage=[],
                findings=[
                    GateFinding(
                        finding_id=group.key,
                        rule_id=group.rule_id,
                        file=group.file,
                        line=group.line,
                        severity=group.severity,
                        verdict=Verdict.CONFIRMED,
                        disposition=DispositionDecision.ACCEPTED,
                        reason="accepted in prior run",
                        hunk_sha256=HUNK_SHA256,
                        body_sha256=BODY_SHA256,
                    )
                ],
                verdict=verdict,
            ),
        )
    return run


def update_source_finding(source: RunHandle, **updates: object) -> None:
    verdict = GateVerdict.model_validate_json(
        (source.dir / "gate-verdict.json").read_text(encoding="utf-8")
    )
    verdict.findings[0] = verdict.findings[0].model_copy(update=updates)
    save_gate_verdict(source.dir, verdict)


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
        [
            "gate",
            "--target",
            "42",
            "--replicas",
            "3",
            "--concurrency",
            "4",
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls[0]["replicas"] == 3
    assert calls[0]["concurrency"] == 4
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


def test_gate_target_invalid_inherit_stops_before_provision_or_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root)
    provision_calls: list[dict[str, object]] = []
    pipeline_calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda spec: target())
    monkeypatch.setattr(
        cli_module,
        "_gate_plan",
        lambda registry_root, resolved, replicas: GatePlan(
            schema_version=1, lane_ids=["lane-a"], replicas=replicas, chunk_count=1
        ),
    )

    def fake_checkout(**kwargs: object) -> Path:
        provision_calls.append(kwargs)
        destination = kwargs["destination"]
        assert isinstance(destination, Path)
        destination.mkdir()
        return destination

    async def fake_execute(**kwargs: object) -> cli_module._PipelineArtifacts:
        pipeline_calls.append(kwargs)
        return current

    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_execute)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            "bad-run-id",
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert "inherit_run_missing" in result.stderr
    assert provision_calls == []
    assert pipeline_calls == []


def test_gate_target_rejects_traversal_inherit_as_invalid_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda spec: target())

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--inherit", "..", "--out", str(tmp_path / "runs")],
    )

    assert result.exit_code == 2
    assert "inherit_run_invalid" in result.stderr


def test_gate_resume_rejects_invalid_run_id_as_user_error(tmp_path: Path) -> None:
    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", "nested/run", "--out", str(tmp_path / "runs")],
    )

    assert result.exit_code == 2
    assert "invalid run ID" in result.stderr
    assert "Traceback" not in result.stderr


def test_gate_rejects_self_inheritance_before_loading_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_load(run_id: str, out_root: Path) -> cli_module._PipelineArtifacts:
        del run_id, out_root
        raise AssertionError("self-inheritance reached run loading")

    monkeypatch.setattr(cli_module, "_load_gate_artifacts", forbidden_load)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            "same-run",
            "--inherit",
            "same-run",
            "--out",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 2
    assert "inherit_self_reference" in result.stderr


@pytest.mark.parametrize(
    ("source_setup", "reason"),
    [
        ("missing_run", "inherit_run_missing"),
        ("missing_verdict", "inherit_verdict_missing"),
        ("target_mismatch", "inherit_target_mismatch"),
    ],
)
def test_gate_inherit_source_errors_before_template_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_setup: str,
    reason: str,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    if source_setup == "missing_verdict":
        inherited_source(out_root, current, write_verdict=False)
    elif source_setup == "target_mismatch":
        inherited_source(out_root, current, pr_number=99)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            "source-run",
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert reason in result.stderr
    assert not (current.run.dir / "gate-dispositions.yaml").exists()


def test_gate_inherit_rejects_symlinked_verdict_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    foreign = tmp_path / "foreign-verdict.json"
    foreign.write_text(
        (source.dir / "gate-verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (source.dir / "gate-verdict.json").unlink()
    (source.dir / "gate-verdict.json").symlink_to(foreign)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert "inherit_verdict_invalid" in result.stderr
    assert not (current.run.dir / "gate-dispositions.yaml").exists()


@pytest.mark.parametrize("source_kind", ["pause", "failure"])
def test_gate_inheritance_source_requires_completed_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    source_verdict = source.load_gate_verdict().model_copy(update={"kind": source_kind})
    save_gate_verdict(source.dir, source_verdict)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert "inherit_source_incomplete" in result.stderr


@pytest.mark.parametrize(
    "counts",
    [
        {},
        {"CONFIRMED": 1, "REJECTED": 0},
        {"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0, "EXTRA": 0},
        {"CONFIRMED": "1", "REJECTED": 0, "UNCERTAIN": 0},
    ],
)
def test_inheritance_source_rejects_non_closed_count_shape(
    tmp_path: Path,
    counts: dict[str, object],
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    verdict_path = source.dir / "gate-verdict.json"
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    raw["counts"] = counts
    raw["findings"] = []
    verdict_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="inherit_verdict_invalid"):
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )


def test_inheritance_source_rejects_blank_accepted_reason(tmp_path: Path) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    verdict_path = source.dir / "gate-verdict.json"
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    raw["findings"][0]["reason"] = "  \t"
    verdict_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="inherit_verdict_invalid"):
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )


def test_inheritance_source_validation_diagnostic_is_bounded_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    verdict_path = source.dir / "gate-verdict.json"
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    raw["findings"][0]["severity"] = "ghp_\u202eSECRET123"
    verdict_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert "inherit_verdict_invalid" in result.stderr
    assert "ghp_SECRET123" not in result.stderr
    assert "[REDACTED]" in result.stderr
    assert len(result.stderr) <= 600


def test_inheritance_target_validation_diagnostic_is_bounded_and_redacted(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    target_path = source.dir / "target.json"
    raw = json.loads(target_path.read_text(encoding="utf-8"))
    token = "github_pat_" + "11AA22BB33CC44DD55EE66FF"
    raw["pr_number"] = token
    target_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )

    detail = str(caught.value)
    assert "inherit_target_invalid" in detail
    assert token not in detail
    assert "[REDACTED]" in detail
    assert len(detail) <= 600


def test_inheritance_target_mismatch_redacts_observed_repo_controls_and_token(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    credential = "github_pat_" + "11AA22BB33CC44DD55EE66FF"
    observed = "github_\x00pat_11AA22BB33CC44DD55EE66FF/repo"
    source.save_target(target().model_copy(update={"repo": observed}))

    with pytest.raises(ValueError) as caught:
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )

    detail = str(caught.value)
    assert "inherit_target_mismatch" in detail
    assert "field=repo" in detail
    assert credential not in detail
    assert "\x00" not in detail
    assert "[REDACTED]" in detail


def test_inheritance_source_repo_identity_is_case_insensitive(tmp_path: Path) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current, repo="OwNeR/RePo")

    loaded = cli_module._load_inherited_dispositions(
        source.run_id,
        current_target=current.target,
        out_root=out_root,
    )

    assert loaded.run_id == source.run_id


@pytest.mark.parametrize(
    ("field", "observed"),
    [("repo", "different/repo"), ("pr_number", 99)],
)
def test_inheritance_target_mismatch_names_differing_field(
    tmp_path: Path,
    field: str,
    observed: object,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    source.save_target(target().model_copy(update={field: observed}))

    with pytest.raises(ValueError) as caught:
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )

    detail = str(caught.value)
    assert "inherit_target_mismatch" in detail
    assert f"field={field}" in detail
    assert "expected=" in detail
    assert f"observed={observed}" in detail


@pytest.mark.parametrize(
    ("field", "observed"),
    [
        ("run_id", "copied-run"),
        ("repo", "different/repo"),
        ("pr_number", 99),
    ],
)
def test_inheritance_verdict_mismatch_names_differing_field(
    tmp_path: Path,
    field: str,
    observed: object,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    verdict_path = source.dir / "gate-verdict.json"
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    raw[field] = observed
    verdict_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        cli_module._load_inherited_dispositions(
            source.run_id,
            current_target=current.target,
            out_root=out_root,
        )

    detail = str(caught.value)
    assert "inherit_verdict_invalid" in detail
    assert f"field={field}" in detail
    assert "expected=" in detail
    assert f"observed={observed}" in detail


def test_inheritance_source_accepts_closed_counts_and_nonblank_reason(tmp_path: Path) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)

    loaded = cli_module._load_inherited_dispositions(
        source.run_id,
        current_target=current.target,
        out_root=out_root,
    )

    assert loaded.counts == {"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0}
    assert loaded.findings[0].reason == "accepted in prior run"


def test_block_verdict_source_counts_mixed_dispositions_as_pair_ambiguity(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current, verdict="BLOCK")
    source_verdict = GateVerdict.model_validate_json(
        (source.dir / "gate-verdict.json").read_text(encoding="utf-8")
    )
    source_verdict.findings[0] = source_verdict.findings[0].model_copy(
        update={"finding_id": "prior-accepted-id"}
    )
    source_verdict.findings.append(
        source_verdict.findings[0].model_copy(
            update={
                "finding_id": "must-fix-id",
                "disposition": DispositionDecision.MUST_FIX,
                "reason": "must still be fixed",
            }
        )
    )
    save_gate_verdict(source.dir, source_verdict)

    loaded = cli_module._load_inherited_dispositions(
        source.run_id,
        current_target=current.target,
        out_root=out_root,
    )

    assert loaded.run_id == source.run_id
    assert loaded.verdict == "BLOCK"
    assert [finding.finding_id for finding in loaded.findings] == [
        "prior-accepted-id",
        "must-fix-id",
    ]

    group = current.merged.groups[0]
    assert current.outcome is not None
    matched = cli_module.match_inherited_dispositions(
        loaded.findings,
        current.merged,
        current.outcome,
        inherited_run_id=source.run_id,
        current_hunk_sha256={group.key: HUNK_SHA256},
    )[group.key]

    assert matched.tier is None
    assert matched.reason == ""
    assert matched.blank_reason == "source_pair_ambiguous"


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


def test_gate_resume_without_dispositions_preserves_completed_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    group = artifacts.merged.groups[0]
    save_gate_verdict(
        artifacts.run.dir,
        GateVerdict(
            run_id=artifacts.run.run_id,
            repo=artifacts.target.repo,
            pr_number=42,
            anchor=GateAnchor(base_sha="a" * 40, head_sha="b" * 40),
            counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
            coverage=artifacts.discovered.coverage,
            findings=[
                GateFinding(
                    finding_id=group.key,
                    rule_id=group.rule_id,
                    file=group.file,
                    line=group.line,
                    severity=group.severity,
                    verdict=Verdict.CONFIRMED,
                    disposition=DispositionDecision.ACCEPTED,
                    reason="completed owner decision",
                    hunk_sha256=HUNK_SHA256,
                    body_sha256=BODY_SHA256,
                )
            ],
            verdict="PASS",
        ),
    )
    json_path = artifacts.run.dir / "gate-verdict.json"
    markdown_path = artifacts.run.dir / "gate-verdict.md"
    original_json = json_path.read_bytes()
    original_markdown = markdown_path.read_bytes()
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root)],
    )

    assert result.exit_code == 2
    assert "verdict_already_completed" in result.stderr
    assert "--inherit" in result.stderr
    assert json_path.read_bytes() == original_json
    assert markdown_path.read_bytes() == original_markdown


def test_gate_resume_rejects_truncated_verdict_as_corrupt_without_rewriting(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    verdict_path = artifacts.run.dir / "gate-verdict.json"
    corrupt_bytes = b'{"run_id":'
    verdict_path.write_bytes(corrupt_bytes)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root)],
    )

    assert result.exit_code == 3
    assert "verdict_artifact_corrupt" in result.stderr
    assert verdict_path.read_bytes() == corrupt_bytes


def test_gate_completed_dry_run_can_be_republished_with_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )
    assert first.exit_code == 0
    verdict_bytes = (artifacts.run.dir / "gate-verdict.json").read_bytes()
    published: list[str] = []

    def successful_publish(**kwargs: object) -> PublishResult:
        assert kwargs["execute"] is True
        published.append(str(kwargs["report_md"]))
        return PublishResult(
            review_url="https://example.test/review/1",
            inline_count=2,
            body_fallback_count=1,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "publish_review", successful_publish)
    second = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root), "--execute"],
    )

    assert second.exit_code == 0, second.stderr
    assert published == [render_gate_verdict(artifacts.run.load_gate_verdict())]
    assert (artifacts.run.dir / "gate-verdict.json").read_bytes() == verdict_bytes
    publish_attempts = json.loads(
        (artifacts.run.dir / "publish-status.json").read_text(encoding="utf-8")
    )
    assert len(publish_attempts) == 2
    publish_status = publish_attempts[-1]
    assert publish_status["mode"] == "execute"
    assert publish_status["ok"] is True
    assert publish_status["detail"] is None
    assert publish_status["republish"] is True
    assert publish_status["inline_count"] == 2
    assert publish_status["body_fallback_count"] == 1


def test_gate_completed_republish_skips_gate_revalidation_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )
    assert first.exit_code == 0, first.stderr
    json_path = artifacts.run.dir / "gate-verdict.json"
    markdown_path = artifacts.run.dir / "gate-verdict.md"
    original_json = json_path.read_bytes()
    original_markdown = markdown_path.read_bytes()
    published: list[str] = []

    monkeypatch.setattr(
        cli_module,
        "query_pull_request",
        lambda repo, number: current_state(head_sha="c" * 40),
    )

    def successful_publish(**kwargs: object) -> PublishResult:
        published.append(str(kwargs["report_md"]))
        return PublishResult(
            review_url="https://example.test/review/immutable",
            inline_count=0,
            body_fallback_count=0,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "publish_review", successful_publish)
    second = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root), "--execute"],
    )

    assert second.exit_code == 0, second.stderr
    assert published == [render_gate_verdict(artifacts.run.load_gate_verdict())]
    assert json_path.read_bytes() == original_json
    assert markdown_path.read_bytes() == original_markdown


@pytest.mark.parametrize("cache_state", ["missing", "stale"])
def test_gate_completed_republish_renders_from_json_when_markdown_cache_is_unusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_state: str,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )
    assert first.exit_code == 0
    markdown_path = artifacts.run.dir / "gate-verdict.md"
    if cache_state == "missing":
        markdown_path.unlink()
    else:
        markdown_path.write_text("# stale pause artifact\n", encoding="utf-8")
    published: list[str] = []

    def successful_publish(**kwargs: object) -> PublishResult:
        published.append(str(kwargs["report_md"]))
        return PublishResult(
            review_url="https://example.test/review/cache",
            inline_count=0,
            body_fallback_count=0,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "publish_review", successful_publish)
    second = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root), "--execute"],
    )

    assert second.exit_code == 0, second.stderr
    assert published == [render_gate_verdict(artifacts.run.load_gate_verdict())]


def test_gate_completed_republish_rejects_symlinked_markdown_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )
    assert first.exit_code == 0
    markdown_path = artifacts.run.dir / "gate-verdict.md"
    markdown_path.unlink()
    secret = tmp_path / "secret.txt"
    secret.write_text("never publish me", encoding="utf-8")
    markdown_path.symlink_to(secret)
    calls = 0

    def forbidden_publish(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError(f"unexpected publish: {kwargs}")

    monkeypatch.setattr(cli_module, "publish_review", forbidden_publish)
    second = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root), "--execute"],
    )

    assert second.exit_code == 3
    assert calls == 0
    assert "never publish me" not in (second.stdout + second.stderr)


def test_gate_successful_dry_run_writes_publish_status_with_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)

    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )

    assert result.exit_code == 0, result.stderr
    attempts = json.loads((artifacts.run.dir / "publish-status.json").read_text(encoding="utf-8"))
    assert len(attempts) == 1
    status = attempts[0]
    assert status["attempted_at"]
    assert status["mode"] == "dry_run"
    assert status["ok"] is True
    assert status["detail"] is None
    assert status["republish"] is False
    assert status["inline_count"] == 0
    assert status["body_fallback_count"] == 0


def test_save_publish_status_migrates_legacy_object_and_appends(tmp_path: Path) -> None:
    run = RunStore(tmp_path / "runs").create(target())
    legacy = {
        "attempted_at": "2026-07-31T00:00:00+00:00",
        "mode": "execute",
        "ok": False,
        "detail": "legacy failure",
        "republish": False,
    }
    (run.dir / "publish-status.json").write_text(json.dumps(legacy), encoding="utf-8")

    cli_module._save_publish_status(
        run,
        attempted_at="2026-07-31T00:01:00+00:00",
        execute=True,
        ok=True,
        detail=None,
        republish=True,
        inline_count=0,
        body_fallback_count=0,
    )

    attempts = json.loads((run.dir / "publish-status.json").read_text(encoding="utf-8"))
    assert attempts[0] == legacy
    assert attempts[1]["ok"] is True
    assert attempts[1]["republish"] is True


def test_save_publish_status_rejects_symlinked_artifact(tmp_path: Path) -> None:
    run = RunStore(tmp_path / "runs").create(target())
    victim = tmp_path / "victim.json"
    victim.write_text("preserve me", encoding="utf-8")
    (run.dir / "publish-status.json").symlink_to(victim)

    with pytest.raises((OSError, ValueError)):
        cli_module._save_publish_status(
            run,
            attempted_at="2026-07-31T00:00:00+00:00",
            execute=False,
            ok=True,
            detail=None,
            republish=False,
            inline_count=0,
            body_fallback_count=0,
        )

    assert victim.read_text(encoding="utf-8") == "preserve me"


def test_gate_failed_publish_writes_redacted_publish_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    token = "github_pat_" + "11AA22BB33CC44DD55EE66FF"

    def failed_publish(**kwargs: object) -> object:
        del kwargs
        raise cli_module.PublishError(f"publish failed with {token}")

    monkeypatch.setattr(cli_module, "publish_review", failed_publish)
    result = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root), "--execute"],
    )

    assert result.exit_code == 3
    attempts = json.loads((artifacts.run.dir / "publish-status.json").read_text(encoding="utf-8"))
    assert len(attempts) == 1
    status = attempts[0]
    assert status["attempted_at"]
    assert status["mode"] == "execute"
    assert status["ok"] is False
    assert status["republish"] is False
    assert "[REDACTED]" in status["detail"]
    assert token not in status["detail"]
    assert token not in result.stderr


def test_gate_transient_publish_failure_retries_existing_completed_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    calls: list[str] = []

    def flaky_publish(**kwargs: object) -> PublishResult:
        calls.append(str(kwargs["report_md"]))
        if len(calls) == 1:
            raise cli_module.PublishError("transient publish failure")
        return PublishResult(
            review_url="https://example.test/review/2",
            inline_count=1,
            body_fallback_count=0,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "publish_review", flaky_publish)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root), "--execute"],
    )
    assert first.exit_code == 3
    verdict_bytes = (artifacts.run.dir / "gate-verdict.json").read_bytes()

    second = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root), "--execute"],
    )

    assert second.exit_code == 0, second.stderr
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert (artifacts.run.dir / "gate-verdict.json").read_bytes() == verdict_bytes
    attempts = json.loads((artifacts.run.dir / "publish-status.json").read_text(encoding="utf-8"))
    assert [attempt["ok"] for attempt in attempts] == [False, True]


def test_gate_completed_verdict_rejects_disposition_regeneration_with_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root)
    patch_target_dependencies(monkeypatch, artifacts)
    first = runner.invoke(
        cli_module.app,
        ["gate", "--target", "42", "--out", str(out_root)],
    )
    assert first.exit_code == 0
    dispositions = tmp_path / "dispositions.yaml"
    dispositions.write_text("schema_version: 1\ndispositions: []\n", encoding="utf-8")

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            artifacts.run.run_id,
            "--dispositions",
            str(dispositions),
            "--out",
            str(out_root),
            "--execute",
        ],
    )

    assert result.exit_code == 2
    assert "verdict_already_completed" in result.stderr


def test_gate_failure_verdict_is_retryable_after_dispositions_are_corrected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("schema_version: 1\ndispositions: []\n", encoding="utf-8")
    first = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            artifacts.run.run_id,
            "--dispositions",
            str(invalid),
            "--out",
            str(out_root),
        ],
    )
    assert first.exit_code == 1
    assert artifacts.run.load_gate_verdict().kind == "failure"

    finding_id = artifacts.merged.groups[0].key
    corrected = tmp_path / "corrected.yaml"
    corrected.write_text(
        "schema_version: 1\ndispositions:\n"
        f"  - finding_id: {finding_id}\n"
        "    decision: accepted\n"
        "    reason: corrected owner decision\n",
        encoding="utf-8",
    )
    second = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            artifacts.run.run_id,
            "--dispositions",
            str(corrected),
            "--out",
            str(out_root),
        ],
    )

    assert second.exit_code == 0, second.stderr
    assert artifacts.run.load_gate_verdict().kind == "completed"


def test_gate_orphan_outcome_key_persists_failure_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    assert artifacts.outcome is not None
    artifacts.outcome.verdicts["orphan-finding"] = Verdict.CONFIRMED
    artifacts.run.save_outcome(artifacts.outcome)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root)],
    )

    assert result.exit_code == 1
    persisted = artifacts.run.load_gate_verdict()
    assert persisted.kind == "failure"
    assert persisted.verdict == "BLOCK"
    assert persisted.findings == []
    assert "orphan-finding" in persisted.failures[0]


def test_gate_full_inheritance_does_not_overwrite_completed_block_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    group = current.merged.groups[0]
    save_gate_verdict(
        current.run.dir,
        GateVerdict(
            run_id=current.run.run_id,
            repo=current.target.repo,
            pr_number=42,
            anchor=GateAnchor(base_sha="a" * 40, head_sha="b" * 40),
            counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
            coverage=current.discovered.coverage,
            findings=[
                GateFinding(
                    finding_id=group.key,
                    rule_id=group.rule_id,
                    file=group.file,
                    line=group.line,
                    severity=group.severity,
                    verdict=Verdict.CONFIRMED,
                    disposition=DispositionDecision.MUST_FIX,
                    reason="must still be fixed",
                    hunk_sha256=HUNK_SHA256,
                    body_sha256=BODY_SHA256,
                )
            ],
            verdict="BLOCK",
        ),
    )
    verdict_path = current.run.dir / "gate-verdict.json"
    original_verdict = verdict_path.read_bytes()
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 2
    assert "verdict_already_completed" in result.stderr
    assert verdict_path.read_bytes() == original_verdict


def test_gate_full_inheritance_replaces_pause_stub_and_proceeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    save_gate_verdict(
        current.run.dir,
        GateVerdict(
            run_id=current.run.run_id,
            repo=current.target.repo,
            pr_number=42,
            anchor=GateAnchor(base_sha="a" * 40, head_sha="b" * 40),
            counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
            coverage=current.discovered.coverage,
            findings=[],
            verdict="BLOCK",
            failures=["actionable findings require explicit dispositions"],
        ),
    )
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 0, result.stderr
    persisted = current.run.load_gate_verdict()
    assert persisted.verdict == "PASS"
    assert persisted.findings[0].inherited_from == source.run_id


def test_gate_inheritance_matcher_invariant_persists_block_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    current.merged.groups[0] = current.merged.groups[0].model_copy(update={"bodies": []})
    current.run.save_merge(current.merged)
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 1
    assert "must contain at least" in result.stderr
    assert "one body" in result.stderr
    persisted = current.run.load_gate_verdict()
    assert persisted.verdict == "BLOCK"
    assert persisted.findings == []
    assert persisted.failures == [
        f"collapsed finding {current.merged.groups[0].key} must contain at least one body"
    ]


def test_gate_resume_without_dispositions_rewrites_existing_pause_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    artifacts = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        artifacts.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    save_gate_verdict(
        artifacts.run.dir,
        GateVerdict(
            run_id=artifacts.run.run_id,
            repo=artifacts.target.repo,
            pr_number=42,
            anchor=GateAnchor(base_sha="a" * 40, head_sha="b" * 40),
            counts={"CONFIRMED": 1, "REJECTED": 0, "UNCERTAIN": 0},
            coverage=artifacts.discovered.coverage,
            findings=[],
            verdict="BLOCK",
            failures=["actionable findings require explicit dispositions"],
        ),
    )
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        ["gate", "--run", artifacts.run.run_id, "--out", str(out_root)],
    )

    assert result.exit_code == 1
    assert "actionable findings require dispositions" in result.stdout
    persisted = artifacts.run.load_gate_verdict()
    assert persisted.findings == []
    assert persisted.failures == ["actionable findings require explicit dispositions"]


@pytest.mark.parametrize("mode", ["target", "run"])
def test_gate_full_tier_one_inheritance_persists_document_and_auto_proceeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    if mode == "target":
        calls = patch_target_dependencies(monkeypatch, current)
        mode_args = ["--target", "42"]
    else:
        calls = []
        save_gate_plan(
            current.run.dir,
            GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
        )
        monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())
        mode_args = ["--run", current.run.run_id]

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            *mode_args,
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == (1 if mode == "target" else 0)
    document = (current.run.dir / "gate-dispositions.yaml").read_text(encoding="utf-8")
    assert "decision: accepted" in document
    assert "inherited_from: source-run" in document
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["findings"][0]["inherited_from"] == source.run_id
    markdown = (current.run.dir / "gate-verdict.md").read_text(encoding="utf-8")
    assert "`source-run`" in markdown
    assert (current.run.dir / "publish-payload.json").is_file()


def test_gate_partial_inheritance_writes_prefilled_template_and_pauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    update_source_finding(source, finding_id="moved-finding-id")
    calls = patch_target_dependencies(monkeypatch, current)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 1
    assert len(calls) == 1
    assert "--inherit source-run" in result.stdout
    template = (current.run.dir / "gate-dispositions.yaml").read_text(encoding="utf-8")
    assert "decision: must_fix" in template
    assert "reason: accepted in prior run" in template
    assert "inherited_from: source-run" in template
    assert "inheritance source=source-run carried=0 prefilled=1 blank=0" in result.stdout
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["inheritance_summary"] == {
        "source_run_id": "source-run",
        "carried": 0,
        "prefilled": 1,
        "blank": 0,
        "reasons": {"finding_id_changed": 1},
    }
    assert not (current.run.dir / "publish-payload.json").exists()


def test_gate_exact_id_with_changed_hunk_digest_pauses_with_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    update_source_finding(source, hunk_sha256="0" * 64)
    patch_target_dependencies(monkeypatch, current)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 1
    template = (current.run.dir / "gate-dispositions.yaml").read_text(encoding="utf-8")
    assert "decision: must_fix" in template
    assert "reason: accepted in prior run" in template
    assert "# blank_reason: content_changed" in template
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["inheritance_summary"]["reasons"] == {"content_changed": 1}
    assert not (current.run.dir / "publish-payload.json").exists()


def test_gate_carried_blocker_reverifies_owner_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True, blocker=True)
    source = inherited_source(out_root, current)
    patch_target_dependencies(monkeypatch, current)
    permission_calls: list[str] = []

    def contributor_permission(repo: str) -> tuple[str, str]:
        permission_calls.append(repo)
        return "contributor", "write"

    monkeypatch.setattr(cli_module, "github_actor_permission", contributor_permission)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 1
    assert permission_calls == ["owner/repo"]
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "BLOCK"
    failure = verdict["failures"][0]
    assert current.merged.groups[0].key in failure
    assert "contributor" in failure
    assert "write" in failure
    assert not (current.run.dir / "publish-payload.json").exists()


@pytest.mark.parametrize(
    ("failed_step", "exit_status", "expected_actor"),
    [
        ("actor_lookup", 17, None),
        ("permission_lookup", 23, "repo-owner"),
    ],
)
def test_gate_redacts_and_labels_carried_blocker_authorization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_step: str,
    exit_status: int,
    expected_actor: str | None,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True, blocker=True)
    source = inherited_source(out_root, current)
    patch_target_dependencies(monkeypatch, current)
    real_permission_lookup = cli_module.github_actor_permission
    secret_token = "github_pat_" + "11AA22BB33CC44DD55EE66FF"
    bearer_secret = "bearer-value-that-must-not-survive"
    fixture_label = f"fixture-{failed_step}-only"

    def failed_permission_lookup(repo: str) -> tuple[str, str]:
        def fake_run(command: list[str]) -> str:
            is_actor_lookup = command[:3] == ["gh", "api", "user"]
            if is_actor_lookup and failed_step == "permission_lookup":
                return "repo-owner\n"
            raise subprocess.CalledProcessError(
                returncode=exit_status,
                cmd=command,
                stderr=(
                    f"{fixture_label}\u202e\u200e\x00\n"
                    f"Authorization: Bearer {bearer_secret}\n"
                    f"token={secret_token}\n" + "bounded diagnostic words " * 80
                ),
            )

        return real_permission_lookup(repo, run=fake_run)

    monkeypatch.setattr(cli_module, "github_actor_permission", failed_permission_lookup)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 3
    persisted = current.run.load_gate_verdict()
    assert persisted.verdict == "BLOCK"
    assert persisted.actor == expected_actor
    failure = persisted.failures[0]
    assert "accepted_blocker_authorization_operational_failure" in failure
    assert current.merged.groups[0].key in failure
    assert f"step={failed_step}" in failure
    assert f"exit status {exit_status}" in failure
    assert fixture_label in failure
    assert "[REDACTED]" in failure
    assert "[truncated]" in failure
    detail = failure.split("; ", maxsplit=1)[1]
    assert len(detail) <= 500
    markdown = (current.run.dir / "gate-verdict.md").read_text(encoding="utf-8")
    persisted_json = (current.run.dir / "gate-verdict.json").read_text(encoding="utf-8")
    for sink in (failure, markdown, persisted_json, result.stderr):
        assert secret_token not in sink
        assert bearer_secret not in sink
        assert "\x00" not in sink
        assert "\u202e" not in sink
        assert "\u200e" not in sink
        assert f"step={failed_step}" in sink
    assert not (current.run.dir / "publish-payload.json").exists()


def test_gate_owner_authorization_requires_nonempty_blocker_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    source = inherited_source(out_root, current)
    patch_target_dependencies(monkeypatch, current)
    monkeypatch.setattr(cli_module, "requires_owner_authorization", lambda *args, **kwargs: True)

    def forbidden_permission(repo: str) -> tuple[str, str]:
        raise AssertionError(f"authorization lookup reached with no blocker IDs for {repo}")

    monkeypatch.setattr(cli_module, "github_actor_permission", forbidden_permission)

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--target",
            "42",
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
        ],
    )

    assert result.exit_code == 1
    assert "accepted blocker IDs" in result.stderr
    persisted = current.run.load_gate_verdict()
    assert any("accepted blocker IDs" in failure for failure in persisted.failures)


@pytest.mark.parametrize("source_case", ["absent", "wrong_run", "unmatched"])
def test_gate_rejects_unbound_inherited_from_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_case: str,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current) if source_case != "absent" else None
    if source_case == "unmatched":
        assert source is not None
        update_source_finding(source, finding_id="other-id", file="src/other.py")
    claim = "other-run" if source_case == "wrong_run" else "source-run"
    finding_id = current.merged.groups[0].key
    dispositions = tmp_path / f"{source_case}.yaml"
    dispositions.write_text(
        "schema_version: 1\ndispositions:\n"
        f"  - finding_id: {finding_id}\n"
        "    decision: accepted\n"
        "    reason: reviewed\n"
        f"    inherited_from: {claim}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())
    args = [
        "gate",
        "--run",
        current.run.run_id,
        "--dispositions",
        str(dispositions),
        "--out",
        str(out_root),
    ]
    if source is not None:
        args.extend(["--inherit", source.run_id])

    result = runner.invoke(cli_module.app, args)

    assert result.exit_code == 1
    assert "inherited_from_unbound" in result.stderr
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert any("inherited_from_unbound" in failure for failure in verdict["failures"])


def test_gate_allows_fresh_disposition_when_inheritance_source_is_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "runs"
    current = prepared_artifacts(out_root, actionable=True)
    save_gate_plan(
        current.run.dir,
        GatePlan(schema_version=1, lane_ids=["lane-a"], replicas=1, chunk_count=1),
    )
    source = inherited_source(out_root, current)
    update_source_finding(source, finding_id="other-id", file="src/other.py")
    finding_id = current.merged.groups[0].key
    dispositions = tmp_path / "fresh.yaml"
    dispositions.write_text(
        "schema_version: 1\ndispositions:\n"
        f"  - finding_id: {finding_id}\n"
        "    decision: accepted\n"
        "    reason: fresh review\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "query_pull_request", lambda repo, number: current_state())

    result = runner.invoke(
        cli_module.app,
        [
            "gate",
            "--run",
            current.run.run_id,
            "--dispositions",
            str(dispositions),
            "--inherit",
            source.run_id,
            "--out",
            str(out_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    verdict = json.loads((current.run.dir / "gate-verdict.json").read_text(encoding="utf-8"))
    assert verdict["findings"][0]["inherited_from"] is None


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
