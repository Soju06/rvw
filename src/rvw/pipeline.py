"""Reusable execution and loading for the ordinary rvw review pipeline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rvw.adjudicate import AdjudicationInfrastructureError, AdjudicationOutcome
from rvw.discover import DiscoverResult, DiscoveryPlan, discover, plan_discovery
from rvw.discovery_cost import (
    DEFAULT_MAX_DISCOVERY_RUNS,
    build_discovery_preflight,
    require_heavy_discovery_acknowledgement,
)
from rvw.dispatch import DEFAULT_DEADLINE_SECONDS
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import MergeResult, merge
from rvw.provenance import stale_install_warning
from rvw.registry import Registry
from rvw.report import render_report
from rvw.runtime_policy import DEFAULT_CODEX_RUNTIME_POLICY, CodexRuntimePolicy
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


def _preflight_runtime_policy(
    runtime: Runtime,
    supplied_policy: CodexRuntimePolicy | None,
) -> CodexRuntimePolicy:
    """Use the dispatched runtime's policy when it exposes one.

    Generic test and integration runtimes need not expose Codex configuration,
    so they may still supply an explicit policy (or use the stable default).
    A Codex runtime must never persist preflight accounting for a different
    policy than it will execute.
    """

    runtime_policy = getattr(runtime, "policy", None)
    if isinstance(runtime_policy, CodexRuntimePolicy):
        if supplied_policy is not None and supplied_policy != runtime_policy:
            raise ValueError("runtime_policy must match the dispatched runtime policy")
        return runtime_policy
    return supplied_policy or DEFAULT_CODEX_RUNTIME_POLICY


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
    preflight: dict[str, object] | None = None


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
    registry: Registry | None,
    lanes_root: Path | None,
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
    planned_discovery: DiscoveryPlan | None = None,
    max_discovery_runs: int = DEFAULT_MAX_DISCOVERY_RUNS,
    allow_heavy_discovery: bool = False,
    runtime_policy: CodexRuntimePolicy | None = None,
    adjudication_runtime: Runtime | None = None,
    expanded_adjudication_runtime: Runtime | None = None,
    host_gate: HostSlotGate | None = None,
    on_pause: MessageSink | None = None,
    on_warning: MessageSink | None = None,
    resume_run: RunHandle | None = None,
) -> PipelineArtifacts | None:
    """Execute and persist DISCOVER, MERGE, ADJUDICATE, and REPORT."""

    if discover_replicas < 1:
        raise ValueError("discover_replicas must be at least 1")
    if adjudicate_replicas < 1:
        raise ValueError("adjudicate_replicas must be at least 1")
    brief = dynamic_brief.read_text(encoding="utf-8") if dynamic_brief is not None else None
    if planned_discovery is None:
        if registry is None or lanes_root is None:
            raise ValueError("registry and lanes_root are required without a discovery plan")
        plan = plan_discovery(
            registry=registry,
            lanes_root=lanes_root,
            target=target,
            brief=brief,
            brief_source="operator" if dynamic_brief is not None else None,
            replicas=discover_replicas,
            lane_filter=[lane.id for lane in active_lanes],
        )
    else:
        plan = planned_discovery
    preflight = build_discovery_preflight(
        plan,
        replicas=discover_replicas,
        max_discovery_runs=max_discovery_runs,
        runtime_policy=_preflight_runtime_policy(runtime, runtime_policy),
    )
    preflight_payload = preflight.payload()
    adjudication_runtime = adjudication_runtime or runtime
    if resume_run is None:
        require_heavy_discovery_acknowledgement(
            preflight,
            allow_heavy_discovery=allow_heavy_discovery,
        )
        run = RunStore(out_root).create(target)
        run.save_target(target)
        run.save_discovery_plan(plan)
        run.save_preflight(preflight_payload)
        run.save_execution_config(
            discover_replicas=discover_replicas,
            adjudicate_replicas=adjudicate_replicas,
            concurrency=concurrency,
            deadline_seconds=deadline_seconds,
            max_discovery_runs=max_discovery_runs,
        )
    else:
        run = resume_run
        if run.load_target() != target:
            raise ValueError("resume run target does not match the requested target")
        if run.load_discovery_plan() != plan:
            raise ValueError("resume discovery plan does not match the persisted plan")
        if run.load_preflight() != preflight_payload:
            raise ValueError("resume preflight does not match the persisted preflight")
        saved_config = run.load_execution_config()
        requested_config = {
            "discover_replicas": discover_replicas,
            "adjudicate_replicas": adjudicate_replicas,
            "concurrency": concurrency,
            "deadline_seconds": deadline_seconds,
            "max_discovery_runs": max_discovery_runs,
        }
        if saved_config != requested_config:
            raise ValueError("resume execution settings do not match the persisted settings")
    if on_warning is not None and (warning := stale_install_warning()) is not None:
        on_warning(warning)
    try:
        prior_attempts = run.load_discovery_progress()
        prior_incomplete_keys = run.load_incomplete_discovery_attempts()
        if prior_incomplete_keys:
            run.finalize_incomplete_discovery_attempts()
    except StageMissing:
        prior_attempts = {}
        prior_incomplete_keys = set()
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
        planned=plan,
        prior_attempts=prior_attempts,
        prior_incomplete_keys=prior_incomplete_keys,
        on_progress=run.append_discovery_progress,
        on_attempt_started=lambda planned_run, attempt, artifact_dir: (
            run.append_discovery_attempt_started(
                planned_run.lane.id,
                planned_run.replica,
                planned_run.chunk,
                attempt,
                artifact_dir,
            )
        ),
    )
    run.save_discover(discovered)
    build = run.load_summary().build
    summary = summarize_run(run.run_id, discovered, build=build)

    lane_tiers = {lane.id: lane.tier for lane in plan.lanes}
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
                preflight=preflight_payload,
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
        preflight=preflight_payload,
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
    try:
        preflight = run.load_preflight()
    except StageMissing:
        preflight = None
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=report_md,
        report_path=run.dir / "report.md",
        summary=summary,
        preflight=preflight,
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
