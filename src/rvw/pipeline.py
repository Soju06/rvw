"""Reusable execution and loading for the ordinary rvw review pipeline."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rvw.adjudicate import AdjudicationInfrastructureError, AdjudicationOutcome
from rvw.checkout import CheckoutVerificationError, verify_checkout
from rvw.discover import DiscoverResult, DiscoveryMode, discover
from rvw.dispatch import DEFAULT_DEADLINE_SECONDS
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import MergeResult, merge
from rvw.provenance import stale_install_warning
from rvw.registry import EffectiveRegistry, Registry
from rvw.report import render_report
from rvw.runtimes import Runtime
from rvw.schema import Verdict
from rvw.store import RunHandle, RunStore, StageMissing
from rvw.summary import RunError, RunSummary, summarize_run
from rvw.target import ResolvedTarget

Adjudicator = Callable[
    ...,
    Awaitable[AdjudicationOutcome],
]
MessageSink = Callable[[str], None]


@dataclass(frozen=True)
class PipelineArtifacts:
    """Completed, persisted outputs from one ordinary review."""

    run: RunHandle
    target: ResolvedTarget
    discovered: DiscoverResult
    merged: MergeResult
    outcome: AdjudicationOutcome | None
    report_md: str
    report_path: Path
    summary: RunSummary | None = None


class PipelineInfrastructureError(RuntimeError):
    """Expected runtime infrastructure failure with persisted partial artifacts."""

    def __init__(self, artifacts: PipelineArtifacts) -> None:
        self.artifacts = artifacts
        message = (
            artifacts.summary.error.message if artifacts.summary and artifacts.summary.error else ""
        )
        super().__init__(message or "review pipeline infrastructure failure")


def optional_outcome(run: RunHandle) -> AdjudicationOutcome | None:
    """Load an outcome when present without hiding other artifact failures."""

    try:
        return run.load_outcome()
    except StageMissing:
        return None


def coverage_totals(discovered: DiscoverResult) -> dict[str, int]:
    return {
        "dispatched": sum(item.dispatched for item in discovered.coverage),
        "valid": sum(item.valid for item in discovered.coverage),
        "findings": sum(item.findings for item in discovered.coverage),
    }


def verdict_counts(outcome: AdjudicationOutcome | None) -> dict[str, int]:
    counts = Counter(outcome.verdicts.values()) if outcome is not None else Counter()
    return {
        "CONFIRMED": counts[Verdict.CONFIRMED],
        "REJECTED": counts[Verdict.REJECTED],
        "UNCERTAIN": counts[Verdict.UNCERTAIN],
    }


async def execute_pipeline(
    *,
    registry: Registry | EffectiveRegistry,
    lanes_root: Path,
    target: ResolvedTarget,
    active_lanes: Sequence[Lane],
    runtime: Runtime,
    adjudicator: Adjudicator,
    repo_dir: Path | None,
    discover_replicas: int,
    adjudicate_replicas: int,
    concurrency: int,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    out_root: Path,
    pause: bool,
    dynamic_brief: Path | None,
    adjudication_runtime: Runtime | None = None,
    expanded_adjudication_runtime: Runtime | None = None,
    host_gate: HostSlotGate | None = None,
    on_pause: MessageSink | None = None,
    on_warning: MessageSink | None = None,
    rule_source_warning: str | None = None,
    discovery_mode: DiscoveryMode = DiscoveryMode.AGENTIC,
    run_handle: RunHandle | None = None,
) -> PipelineArtifacts | None:
    """Execute and persist DISCOVER, MERGE, ADJUDICATE, and REPORT."""

    if discover_replicas < 1:
        raise ValueError("discover_replicas must be at least 1")
    if adjudicate_replicas < 1:
        raise ValueError("adjudicate_replicas must be at least 1")
    adjudication_runtime = adjudication_runtime or runtime
    if discovery_mode is DiscoveryMode.AGENTIC:
        if target.base_sha is None:
            raise CheckoutVerificationError(
                "missing-base", "agentic discovery requires a target base SHA"
            )
        if repo_dir is None:
            raise CheckoutVerificationError(
                "missing-checkout", "agentic discovery requires a provisioned checkout"
            )
        verify_checkout(repo_dir, base_sha=target.base_sha, head_sha=target.head_sha)
    run = run_handle or RunStore(out_root).create(target)
    if on_warning is not None and (warning := stale_install_warning()) is not None:
        on_warning(warning)
    run.save_target(target)
    if rule_source_warning:
        (run.dir / "metadata.json").write_text(
            json.dumps({"rule_source_warning": rule_source_warning}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    brief = dynamic_brief.read_text(encoding="utf-8") if dynamic_brief is not None else None
    discovered = await discover(
        registry=registry,
        lanes_root=lanes_root,
        target=target,
        runtime=runtime,
        out_root=run.dir / "discover-runtime",
        brief=brief,
        brief_source="operator" if dynamic_brief is not None else None,
        replicas=discover_replicas,
        concurrency=concurrency,
        deadline_seconds=deadline_seconds,
        host_gate=host_gate,
        mode=discovery_mode,
        repo_dir=repo_dir,
    )
    run.save_discover(discovered)
    build = run.load_summary().build
    summary = summarize_run(run.run_id, discovered, build=build)

    lane_tiers = {lane.id: lane.tier for lane in active_lanes}
    merged = merge(discovered.findings, lane_tiers=lane_tiers)
    run.save_merge(merged)

    if pause:
        run.save_summary(summary)
        if on_pause is not None:
            on_pause(f"paused after MERGE — resume: rvw report --run {run.run_id}")
        return None

    outcome: AdjudicationOutcome | None = None
    if repo_dir is None:
        if on_warning is not None:
            on_warning(
                "warning: --repo-dir omitted; skipping adjudication. "
                "Checkout provisioning is the operator's job in Phase 4."
            )
    else:
        expanded_runtime_kwargs: dict[str, Runtime] = {}
        if expanded_adjudication_runtime is not None:
            expanded_runtime_kwargs["expanded_runtime"] = expanded_adjudication_runtime
        try:
            outcome = await adjudicator(
                merged,
                target=target,
                runtime=adjudication_runtime,
                repo_dir=repo_dir,
                out_root=run.dir / "adjudicate-runtime",
                replicas=adjudicate_replicas,
                concurrency=concurrency,
                deadline_seconds=deadline_seconds,
                host_gate=host_gate,
                **expanded_runtime_kwargs,
            )
        except AdjudicationInfrastructureError as exc:
            error = RunError(
                stage="adjudication",
                reason="no-valid-output",
                message=str(exc),
                attempts=exc.attempts,
            )
            failed_summary = summarize_run(run.run_id, discovered, error=error, build=build)
            report_md = render_report(
                target=target,
                merged=merged,
                outcome=None,
                coverage=discovered.coverage,
                budget=discovered.budget,
                synthesis=None,
                summary=failed_summary,
            )
            run.save_report(report_md)
            run.save_summary(failed_summary)
            artifacts = PipelineArtifacts(
                run=run,
                target=target,
                discovered=discovered,
                merged=merged,
                outcome=None,
                report_md=report_md,
                report_path=run.dir / "report.md",
                summary=failed_summary,
            )
            raise PipelineInfrastructureError(artifacts) from exc
        run.save_outcome(outcome)

    report_md = render_report(
        target=target,
        merged=merged,
        outcome=outcome,
        coverage=discovered.coverage,
        budget=discovered.budget,
        synthesis=None,
        summary=summary,
    )
    if rule_source_warning:
        report_md = f"> {rule_source_warning}\n\n{report_md}"
    run.save_report(report_md)
    run.save_summary(summary)
    report_path = run.dir / "report.md"
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report_md,
        report_path=report_path,
        summary=summary,
    )


def load_pipeline_artifacts(
    run_id: str,
    out_root: Path,
    *,
    require_outcome: bool,
) -> PipelineArtifacts:
    """Load one persisted ordinary run without repeating model work."""

    run = RunStore(out_root).open(run_id)
    target = run.load_target()
    discovered = run.load_discover()
    merged = run.load_merge()
    outcome = run.load_outcome() if require_outcome else optional_outcome(run)
    report_md = run.load_report()
    try:
        summary = run.load_summary()
    except StageMissing:
        summary = summarize_run(run.run_id, discovered)
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report_md,
        report_path=run.dir / "report.md",
        summary=summary,
    )


__all__ = [
    "PipelineArtifacts",
    "PipelineInfrastructureError",
    "coverage_totals",
    "execute_pipeline",
    "load_pipeline_artifacts",
    "optional_outcome",
    "verdict_counts",
]
