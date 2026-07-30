"""Reusable execution and loading for the ordinary rvw review pipeline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, discover
from rvw.lane import Lane
from rvw.merge import MergeResult, merge
from rvw.registry import Registry
from rvw.report import render_report
from rvw.runtimes import Runtime
from rvw.schema import Verdict
from rvw.store import RunHandle, RunStore, StageMissing
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
    registry: Registry,
    lanes_root: Path,
    target: ResolvedTarget,
    active_lanes: Sequence[Lane],
    runtime: Runtime,
    adjudicator: Adjudicator,
    repo_dir: Path | None,
    replicas: int,
    out_root: Path,
    pause: bool,
    dynamic_brief: Path | None,
    on_pause: MessageSink | None = None,
    on_warning: MessageSink | None = None,
) -> PipelineArtifacts | None:
    """Execute and persist DISCOVER, MERGE, ADJUDICATE, and REPORT."""

    run = RunStore(out_root).create(target)
    run.save_target(target)
    brief = dynamic_brief.read_text(encoding="utf-8") if dynamic_brief is not None else None
    discovered = await discover(
        registry=registry,
        lanes_root=lanes_root,
        target=target,
        runtime=runtime,
        out_root=run.dir / "discover-runtime",
        brief=brief,
        brief_source="operator" if dynamic_brief is not None else None,
        replicas=replicas,
    )
    run.save_discover(discovered)

    lane_tiers = {lane.id: lane.tier for lane in active_lanes}
    merged = merge(discovered.findings, lane_tiers=lane_tiers)
    run.save_merge(merged)

    if pause:
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
        outcome = await adjudicator(
            merged,
            target=target,
            runtime=runtime,
            repo_dir=repo_dir,
            out_root=run.dir / "adjudicate-runtime",
            replicas=replicas,
        )
        run.save_outcome(outcome)

    report_md = render_report(
        target=target,
        merged=merged,
        outcome=outcome,
        coverage=discovered.coverage,
        budget=discovered.budget,
        synthesis=None,
    )
    run.save_report(report_md)
    report_path = run.dir / "report.md"
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report_md,
        report_path=report_path,
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
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report_md,
        report_path=run.dir / "report.md",
    )


__all__ = [
    "PipelineArtifacts",
    "coverage_totals",
    "execute_pipeline",
    "load_pipeline_artifacts",
    "optional_outcome",
    "verdict_counts",
]
