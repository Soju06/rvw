from __future__ import annotations

from pathlib import Path

import pytest

import rvw.cli as cli_module
from rvw.adjudicate import (
    AdjudicationAttempt,
    AdjudicationInfrastructureError,
    AdjudicationOutcome,
)
from rvw.discover import DiscoverResult, EnrichedFinding, LaneCoverage, RunCoverage
from rvw.merge import merge
from rvw.report import render_report
from rvw.runtimes import RunDiagnostic
from rvw.schema import Severity, Tier, Verdict
from rvw.store import RunStore
from rvw.summary import ReviewStatus, summarize_run
from rvw.target import ResolvedTarget


def target_fixture() -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
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
    )


def coverage(
    lane_id: str,
    *,
    valid: bool,
    findings: int = 0,
    reason: str | None = None,
) -> LaneCoverage:
    diagnostic = None
    if not valid:
        diagnostic = RunDiagnostic(
            exit_code=0,
            log_path=f"/tmp/{lane_id}/r1/run.log",
            log_bytes=12,
            output_path=f"/tmp/{lane_id}/r1/out.json",
            output_bytes=0 if reason == "empty" else None,
        )
    return LaneCoverage(
        lane_id=lane_id,
        dispatched=1,
        valid=int(valid),
        findings=findings,
        runs=[
            RunCoverage(
                replica=1,
                chunk=1,
                valid=valid,
                findings=findings,
                invalid_reason=reason,
                attempts=[
                    {
                        "attempt": 1,
                        "valid": valid,
                        "invalid_reason": reason,
                    }
                ],
                diagnostic=diagnostic,
            )
        ],
    )


def finding(lane_id: str) -> EnrichedFinding:
    return EnrichedFinding(
        rule_id=f"{lane_id}/rule",
        file="src/app.py",
        hunk_id="src/app.py@@-1+1@@",
        line=1,
        severity=Severity.WARNING,
        body="Security finding survives partial discovery.",
        anchorable=True,
        lane_id=lane_id,
        replica=1,
    )


def test_missing_lane_with_valid_findings_is_degraded() -> None:
    discovered = DiscoverResult(
        lane_results={},
        findings=[finding("security")],
        coverage=[
            coverage("security", valid=True, findings=1),
            coverage("correctness", valid=False, reason="missing"),
        ],
    )

    summary = summarize_run("run-1", discovered)

    assert summary.status is ReviewStatus.DEGRADED
    assert summary.coverage_totals.model_dump() == {
        "dispatched": 2,
        "valid": 1,
        "findings": 1,
    }
    assert [lane.lane_id for lane in summary.failed_lanes] == ["correctness"]
    assert summary.failed_lanes[0].failures[0].reason == "missing"


def test_every_activated_lane_invalid_is_failed() -> None:
    discovered = DiscoverResult(
        lane_results={},
        findings=[],
        coverage=[
            coverage("security", valid=False, reason="empty"),
            coverage("correctness", valid=False, reason="schema-invalid"),
        ],
    )

    summary = summarize_run("run-2", discovered)

    assert summary.status is ReviewStatus.FAILED
    assert summary.coverage_totals.valid == 0
    assert summary.coverage_totals.findings == 0
    assert {lane.lane_id for lane in summary.failed_lanes} == {
        "security",
        "correctness",
    }


def test_valid_security_finding_survives_schema_invalid_lane_in_partial_report() -> None:
    security_finding = finding("security")
    discovered = DiscoverResult(
        lane_results={},
        findings=[security_finding],
        coverage=[
            coverage("security", valid=True, findings=1),
            coverage("correctness", valid=False, reason="schema-invalid"),
        ],
    )
    merged = merge(discovered.findings, lane_tiers={"security": Tier.BASE})
    summary = summarize_run("run-3", discovered)

    report = render_report(
        target=target_fixture(),
        merged=merged,
        outcome=None,
        coverage=discovered.coverage,
        budget=None,
        summary=summary,
    )

    assert len(merged.groups) == 1
    assert "Security finding survives partial discovery." in report
    assert "status: `degraded`" in report
    assert "partial" in report
    assert "correctness" in report
    assert "schema-invalid" in report


async def test_failed_readjudication_preserves_existing_outcome_and_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = target_fixture()
    run = RunStore(tmp_path).create(target)
    discovered = DiscoverResult(
        lane_results={},
        findings=[finding("security")],
        coverage=[coverage("security", valid=True, findings=1)],
    )
    merged = merge(discovered.findings, lane_tiers={"security": Tier.BASE})
    group_key = merged.groups[0].key
    old_outcome = AdjudicationOutcome(
        verdicts={group_key: Verdict.CONFIRMED},
        reasons={group_key: "old reason"},
        evidence={group_key: "old evidence"},
        replica_votes={group_key: [Verdict.CONFIRMED]},
        unresolved=[],
        coerced_rejections=0,
    )
    run.save_target(target)
    run.save_discover(discovered)
    run.save_merge(merged)
    run.save_outcome(old_outcome)
    run.save_report("old report\n")
    outcome_before = (run.dir / "outcome.json").read_bytes()
    report_before = (run.dir / "report.md").read_bytes()
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()

    async def fail_adjudication(*args: object, **kwargs: object) -> AdjudicationOutcome:
        del args, kwargs
        raise AdjudicationInfrastructureError(
            "initial",
            [
                AdjudicationAttempt(
                    wave="initial",
                    replica=1,
                    reason="missing",
                    artifact_dir="/tmp/readjudicate/initial/r1",
                )
            ],
        )

    monkeypatch.setattr(cli_module, "adjudicate", fail_adjudication)

    with pytest.raises(AdjudicationInfrastructureError):
        await cli_module._adjudicate_existing_run(
            run_id=run.run_id,
            repo_dir=repo_dir,
            out_root=tmp_path,
            replicas=1,
            concurrency=1,
            deadline_seconds=30,
            host_gate=None,
        )

    assert (run.dir / "outcome.json").read_bytes() == outcome_before
    assert (run.dir / "report.md").read_bytes() == report_before


async def test_readjudication_constructs_its_runtime_with_the_resolved_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The re-adjudication construction site must carry the resolved policy, not the default."""

    from rvw.runtime_policy import CodexRuntimePolicy
    from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode

    target = target_fixture()
    run = RunStore(tmp_path).create(target)
    discovered = DiscoverResult(
        lane_results={},
        findings=[finding("security")],
        coverage=[coverage("security", valid=True, findings=1)],
    )
    merged = merge(discovered.findings, lane_tiers={"security": Tier.BASE})
    group_key = merged.groups[0].key
    run.save_target(target)
    run.save_discover(discovered)
    run.save_merge(merged)
    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()
    constructed: list[CodexRuntime] = []

    class RecordingRuntime(CodexRuntime):
        def __init__(
            self, *, policy: CodexRuntimePolicy, mode: CodexRuntimeMode = CodexRuntimeMode.AGENTIC
        ) -> None:
            super().__init__(policy=policy, mode=mode)
            constructed.append(self)

        async def execute_raw(self, **kwargs):
            # Keep this construction test offline; synthesis runtime failure is nonfatal.
            raise RuntimeError("scripted synthesis failure")

    observed: dict[str, object] = {}

    async def fake_adjudicate(*args: object, **kwargs: object) -> AdjudicationOutcome:
        del args
        observed.update(kwargs)
        return AdjudicationOutcome(
            verdicts={group_key: Verdict.CONFIRMED},
            reasons={group_key: "verified"},
            evidence={group_key: "source quote"},
            replica_votes={group_key: [Verdict.CONFIRMED]},
            unresolved=[],
            coerced_rejections=0,
        )

    monkeypatch.setattr(cli_module, "CodexRuntime", RecordingRuntime)
    monkeypatch.setattr(cli_module, "adjudicate", fake_adjudicate)
    policy = CodexRuntimePolicy(model="gpt-6-astra", reasoning_effort="medium")

    report_path = await cli_module._adjudicate_existing_run(
        run_id=run.run_id,
        repo_dir=repo_dir,
        out_root=tmp_path,
        replicas=1,
        concurrency=1,
        deadline_seconds=30,
        host_gate=None,
        runtime_policy=policy,
    )

    assert report_path == run.dir / "report.md"
    assert len(constructed) == 2
    assert observed["runtime"] is constructed[0]
    assert constructed[0].policy == policy
    assert constructed[0].policy.reasoning_summary == "detailed"
    assert constructed[1].policy == policy
    assert constructed[1].mode is CodexRuntimeMode.TOOL_LESS
    assert run.load_summary().synthesis.status.startswith("fallback:")
