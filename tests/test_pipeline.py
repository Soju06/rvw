from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast

import pytest

import rvw.pipeline as pipeline_module
from rvw.discover import DiscoverResult, DiscoveryPlan, LaneCoverage, RunCoverage, plan_discovery
from rvw.discovery_cost import DiscoveryCostError
from rvw.dispatch import DEFAULT_DEADLINE_SECONDS
from rvw.lane import load_lane
from rvw.pipeline import execute_pipeline
from rvw.registry import Registry
from rvw.runtime_policy import DEFAULT_CODEX_RUNTIME_POLICY, CodexRuntimePolicy
from rvw.runtimes import RunResult, RunStatus
from rvw.runtimes.codex import CodexRuntime
from rvw.schema import RuntimeLaneOutput, Tier
from rvw.target import ResolvedTarget


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
        repo="owner/repo",
        base_sha="0" * 40,
        head_sha="1" * 40,
        changed_paths=["a.py"],
        diff="diff --git a/a.py b/a.py\n",
    )


def test_execute_pipeline_exposes_only_split_replica_parameters() -> None:
    parameters = inspect.signature(execute_pipeline).parameters

    assert "replicas" not in parameters
    assert "discover_replicas" in parameters
    assert "adjudicate_replicas" in parameters
    assert "deadline_seconds" in parameters


def test_execute_pipeline_preserves_default_deadline() -> None:
    parameter = inspect.signature(execute_pipeline).parameters["deadline_seconds"]

    assert parameter.default == DEFAULT_DEADLINE_SECONDS


@pytest.mark.parametrize(
    ("discover_replicas", "adjudicate_replicas", "message"),
    [
        (0, 3, "discover_replicas must be at least 1"),
        (1, 0, "adjudicate_replicas must be at least 1"),
    ],
)
async def test_execute_pipeline_validates_both_replica_counts_before_creating_a_run(
    tmp_path: Path,
    discover_replicas: int,
    adjudicate_replicas: int,
    message: str,
) -> None:
    unused: Any = None

    with pytest.raises(ValueError, match=message):
        await execute_pipeline(
            registry=unused,
            lanes_root=tmp_path,
            target=target(),
            active_lanes=[],
            runtime=unused,
            adjudicator=unused,
            repo_dir=None,
            discover_replicas=discover_replicas,
            adjudicate_replicas=adjudicate_replicas,
            concurrency=8,
            deadline_seconds=600,
            out_root=tmp_path / "runs",
            pause=False,
            dynamic_brief=None,
        )

    assert not (tmp_path / "runs").exists()


async def test_execute_pipeline_rejects_unacknowledged_heavy_discovery_before_run(
    tmp_path: Path,
) -> None:
    unused: Any = None
    lanes_root = tmp_path / "lanes"
    lane_path = lanes_root / "base" / "quality.md"
    lane_path.parent.mkdir(parents=True)
    lane_path.write_text(
        """---
lane: quality
tier: base
cost: light
rules:
  - quality/rule
---

Review the diff.
""",
        encoding="utf-8",
    )
    registry = Registry.model_validate(
        {"layers": [{"id": "base", "tier": "base", "lanes": ["quality"]}]}
    )

    with pytest.raises(DiscoveryCostError, match="allow-heavy-discovery"):
        await execute_pipeline(
            registry=registry,
            lanes_root=lanes_root,
            target=target(),
            active_lanes=[load_lane(lane_path)],
            runtime=unused,
            adjudicator=unused,
            repo_dir=None,
            discover_replicas=2,
            adjudicate_replicas=1,
            concurrency=1,
            out_root=tmp_path / "runs",
            pause=False,
            dynamic_brief=None,
            max_discovery_runs=12,
            allow_heavy_discovery=False,
            runtime_policy=DEFAULT_CODEX_RUNTIME_POLICY,
        )

    assert not (tmp_path / "runs").exists()


async def test_execute_pipeline_rejects_a_planned_replica_count_mismatch(
    tmp_path: Path,
) -> None:
    unused: Any = None
    lanes_root = tmp_path / "lanes"
    lane_path = lanes_root / "base" / "quality.md"
    lane_path.parent.mkdir(parents=True)
    lane_path.write_text(
        """---
lane: quality
tier: base
cost: light
rules:
  - quality/rule
---

Review the diff.
""",
        encoding="utf-8",
    )
    registry = Registry.model_validate(
        {"layers": [{"id": "base", "tier": "base", "lanes": ["quality"]}]}
    )
    planned = plan_discovery(
        registry=registry,
        lanes_root=lanes_root,
        target=target(),
        replicas=2,
    )

    with pytest.raises(ValueError, match=r"planned discovery replicas .* must match"):
        await execute_pipeline(
            registry=registry,
            lanes_root=lanes_root,
            target=target(),
            active_lanes=[],
            runtime=unused,
            adjudicator=unused,
            repo_dir=None,
            discover_replicas=1,
            adjudicate_replicas=1,
            concurrency=1,
            out_root=tmp_path / "runs",
            pause=False,
            dynamic_brief=None,
            planned_discovery=planned,
            allow_heavy_discovery=True,
        )

    assert not (tmp_path / "runs").exists()


async def test_execute_pipeline_plans_only_the_supplied_active_lanes_and_persists_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lanes_root = tmp_path / "lanes"
    for lane_id in ("selected", "outside-scope"):
        path = lanes_root / "base" / f"{lane_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"""---
lane: {lane_id}
tier: base
cost: light
rules:
  - {lane_id}/rule
---

Review the diff.
""",
            encoding="utf-8",
        )
    registry = Registry.model_validate(
        {"layers": [{"id": "base", "tier": "base", "lanes": ["selected", "outside-scope"]}]}
    )
    observed_lanes: list[str] = []
    policy = CodexRuntimePolicy(model="gpt-test", reasoning_effort="high")

    async def fake_discover(**kwargs: object) -> DiscoverResult:
        plan = cast(DiscoveryPlan, kwargs["planned"])
        observed_lanes.extend(lane.id for lane in plan.lanes)
        return DiscoverResult(lane_results={}, findings=[], coverage=[], budget=plan.budget)

    monkeypatch.setattr(pipeline_module, "discover", fake_discover)
    selected = load_lane(lanes_root / Tier.BASE.value / "selected.md")

    artifacts = await execute_pipeline(
        registry=registry,
        lanes_root=lanes_root,
        target=target(),
        active_lanes=[selected],
        runtime=CodexRuntime(policy=policy),
        adjudicator=cast(Any, None),
        repo_dir=None,
        discover_replicas=1,
        adjudicate_replicas=1,
        concurrency=1,
        out_root=tmp_path / "runs",
        pause=False,
        dynamic_brief=None,
        allow_heavy_discovery=True,
    )

    assert observed_lanes == ["selected"]
    assert artifacts is not None
    assert artifacts.preflight is not None
    assert artifacts.preflight["initial_runs"] == 1
    assert artifacts.preflight["runtime"] == policy.payload()
    assert artifacts.run.load_preflight() == artifacts.preflight


async def test_execute_pipeline_persists_progress_and_reuses_it_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lanes_root = tmp_path / "lanes"
    lane_path = lanes_root / "base" / "quality.md"
    lane_path.parent.mkdir(parents=True)
    lane_path.write_text(
        """---
lane: quality
tier: base
cost: light
rules:
  - quality/rule
---

Review the diff.
""",
        encoding="utf-8",
    )
    registry = Registry.model_validate(
        {"layers": [{"id": "base", "tier": "base", "lanes": ["quality"]}]}
    )
    selected = load_lane(lane_path)
    runtime_result = RunResult(
        lane_id="quality",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="clean", findings=[]),
        invalid_reason=None,
        wall_seconds=1.0,
        artifact_dir=tmp_path / "runtime" / "quality" / "r1",
    )

    async def interrupted_discover(**kwargs: object) -> DiscoverResult:
        callback = cast(Any, kwargs["on_progress"])
        callback(runtime_result)
        raise RuntimeError("interrupted after first completed run")

    monkeypatch.setattr(pipeline_module, "discover", interrupted_discover)
    with pytest.raises(RuntimeError, match="interrupted"):
        await execute_pipeline(
            registry=registry,
            lanes_root=lanes_root,
            target=target(),
            active_lanes=[selected],
            runtime=cast(Any, None),
            adjudicator=cast(Any, None),
            repo_dir=None,
            discover_replicas=1,
            adjudicate_replicas=1,
            concurrency=1,
            deadline_seconds=600,
            out_root=tmp_path / "runs",
            pause=False,
            dynamic_brief=None,
            allow_heavy_discovery=True,
        )

    run = next((tmp_path / "runs").iterdir())
    resumed_run = pipeline_module.RunStore(tmp_path / "runs").open(run.name)
    plan = resumed_run.load_discovery_plan()
    assert resumed_run.load_discovery_progress() == {("quality", 1, 1): [runtime_result]}

    async def resumed_discover(**kwargs: object) -> DiscoverResult:
        assert kwargs["planned"] == plan
        assert kwargs["prior_attempts"] == {("quality", 1, 1): [runtime_result]}
        return DiscoverResult(
            lane_results={"quality": [runtime_result]},
            findings=[],
            coverage=[
                LaneCoverage(
                    lane_id="quality",
                    dispatched=1,
                    valid=1,
                    findings=0,
                    runs=[
                        RunCoverage(
                            replica=1,
                            chunk=1,
                            valid=True,
                            findings=0,
                            invalid_reason=None,
                            attempts=[{"attempt": 1, "valid": True, "invalid_reason": None}],
                        )
                    ],
                )
            ],
            budget=plan.budget,
        )

    monkeypatch.setattr(pipeline_module, "discover", resumed_discover)
    artifacts = await execute_pipeline(
        registry=registry,
        lanes_root=lanes_root,
        target=target(),
        active_lanes=plan.lanes,
        runtime=cast(Any, None),
        adjudicator=cast(Any, None),
        repo_dir=None,
        discover_replicas=1,
        adjudicate_replicas=1,
        concurrency=1,
        deadline_seconds=600,
        out_root=tmp_path / "runs",
        pause=False,
        dynamic_brief=None,
        planned_discovery=plan,
        allow_heavy_discovery=False,
        resume_run=resumed_run,
    )

    assert artifacts is not None
    assert artifacts.run.run_id == resumed_run.run_id
