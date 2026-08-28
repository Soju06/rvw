from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

import rvw.discover as discover_module
from rvw.diffbudget import EmptyReviewDiffError
from rvw.discover import (
    IncompleteDiscoveryError,
    RunCoverage,
    discover,
    plan_discovery,
    remaining_discovery_plan,
    resolve_lane_path,
)
from rvw.discovery_cost import build_discovery_preflight
from rvw.dispatch import DEFAULT_DEADLINE_SECONDS, DispatchOutcome, PlannedRun
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import merge
from rvw.registry import Registry
from rvw.runtime_policy import DEFAULT_CODEX_RUNTIME_POLICY
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, Runtime
from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier
from rvw.target import ResolvedTarget


def write_lane(root: Path, lane_id: str, tier: Tier, *, cost: str = "normal") -> Path:
    relative_id = lane_id.removeprefix(f"{tier.value}/")
    path = root / tier.value / f"{relative_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = lane_id.split("/", maxsplit=1)[0]
    path.write_text(
        "\n".join(
            [
                "---",
                f"lane: {lane_id}",
                f"tier: {tier.value}",
                f"cost: {cost}",
                "rules:",
                f"  - {prefix}/rule",
                "---",
                "",
                f"Review as {lane_id}.",
            ]
        ),
        encoding="utf-8",
    )
    return path


def target(*, pr: bool = False) -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr" if pr else "commit",
        repo="fixture/local",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py"],
        diff=(
            "diff --git a/src/a.py b/src/a.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/a.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+one = 1\n"
            "+two = 2\n"
        ),
        pr_number=12 if pr else None,
        pr_title="Add a thing" if pr else None,
        pr_body="It should stay correct." if pr else None,
    )


class FakeRuntime(Runtime):
    name = "fake"

    def __init__(
        self,
        *,
        findings: dict[str, list[RuntimeFinding]] | None = None,
        invalid_lanes: set[str] | None = None,
        statuses: dict[str, Sequence[RunStatus]] | None = None,
        invalid_reasons: dict[str, Sequence[str]] | None = None,
    ) -> None:
        self.findings = findings or {}
        self.invalid_lanes = invalid_lanes or set()
        self.statuses = statuses or {}
        self.invalid_reasons = invalid_reasons or {}
        self.prompts: list[tuple[str, str]] = []
        self.calls: list[tuple[str, int]] = []
        self.run_dirs: list[Path] = []

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
    ) -> RunResult:
        del deadline_seconds
        replica = int(run_dir.name.removeprefix("r"))
        self.prompts.append((lane.id, prompt))
        self.calls.append((lane.id, replica))
        self.run_dirs.append(run_dir)
        call_index = sum(call_lane == lane.id for call_lane, _replica in self.calls) - 1
        scripted = self.statuses.get(lane.id, ())
        status = (
            scripted[call_index]
            if call_index < len(scripted)
            else RunStatus.INVALID
            if lane.id in self.invalid_lanes
            else RunStatus.VALID
        )
        if status is RunStatus.INVALID:
            reasons = self.invalid_reasons.get(lane.id, ())
            invalid_reason = (
                reasons[call_index] if call_index < len(reasons) else "scripted invalid"
            )
            return RunResult(
                lane_id=lane.id,
                replica=replica,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason=invalid_reason,
                wall_seconds=0,
                artifact_dir=run_dir,
            )
        return RunResult(
            lane_id=lane.id,
            replica=replica,
            status=RunStatus.VALID,
            output=RuntimeLaneOutput(verdict="PASS", findings=self.findings.get(lane.id, [])),
            invalid_reason=None,
            wall_seconds=0,
            artifact_dir=run_dir,
        )


def registry(*lane_entries: tuple[str, Tier]) -> Registry:
    return Registry.model_validate(
        {
            "layers": [
                {
                    "id": f"layer-{index}",
                    "tier": tier.value,
                    "lanes": [lane_id],
                }
                for index, (lane_id, tier) in enumerate(lane_entries)
            ]
        }
    )


def test_resolve_lane_path_uses_owning_tier_for_all_shapes(tmp_path: Path) -> None:
    base = write_lane(tmp_path, "slop-hygiene", Tier.BASE)
    scope = write_lane(tmp_path, "frontend/skeleton-parity", Tier.SCOPE)
    dynamic = write_lane(tmp_path, "dynamic/goal-parity", Tier.DYNAMIC)

    assert resolve_lane_path(tmp_path, "slop-hygiene", Tier.BASE) == base
    assert resolve_lane_path(tmp_path, "frontend/skeleton-parity", Tier.SCOPE) == scope
    assert resolve_lane_path(tmp_path, "dynamic/goal-parity", Tier.DYNAMIC) == dynamic


def test_discover_defaults_to_one_replica() -> None:
    assert inspect.signature(discover).parameters["replicas"].default == 1


def test_plan_discovery_builds_the_exact_initial_prompts_for_dispatch(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    reg = registry(("slop-hygiene", Tier.BASE), ("dynamic/goal-parity", Tier.DYNAMIC))

    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(pr=True),
        replicas=2,
    )

    assert [run.lane.id for run in plan.runs] == [
        "slop-hygiene",
        "slop-hygiene",
        "dynamic/goal-parity",
        "dynamic/goal-parity",
    ]
    assert plan.initial_runs == 4
    assert plan.retry_upper_bound == 8
    assert plan.initial_prompt_characters == sum(len(run.prompt) for run in plan.runs)
    assert all(run.prompt for run in plan.runs)
    assert "UNVERIFIED claim of intent" in plan.runs[2].prompt


def test_discovery_preflight_identifies_every_explicit_heavy_condition(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    plan = plan_discovery(
        registry=registry(("slop-hygiene", Tier.BASE), ("dynamic/goal-parity", Tier.DYNAMIC)),
        lanes_root=lanes_root,
        target=target(pr=True),
        replicas=2,
    )

    preflight = build_discovery_preflight(
        plan,
        replicas=2,
        max_discovery_runs=7,
        runtime_policy=DEFAULT_CODEX_RUNTIME_POLICY,
    )

    assert preflight.heavy_discovery_reasons == (
        "discovery_replicas=2",
        "retry_upper_bound=8 exceeds max_discovery_runs=7",
        "reasoning_effort=max",
    )
    assert preflight.requires_allow_heavy_discovery is True


def test_remaining_preflight_counts_only_remaining_lane_chunks(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "first", Tier.BASE)
    write_lane(lanes_root, "second", Tier.BASE)
    plan = plan_discovery(
        registry=registry(("first", Tier.BASE), ("second", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    reused = RunResult(
        lane_id="first",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )

    preflight = build_discovery_preflight(
        remaining_discovery_plan(plan, {("first", 1, 1): reused}),
        replicas=1,
        max_discovery_runs=12,
        runtime_policy=DEFAULT_CODEX_RUNTIME_POLICY,
    )

    assert (preflight.lanes, preflight.chunks, preflight.initial_runs) == (1, 1, 1)


def test_resolve_lane_path_error_lists_attempted_path(tmp_path: Path) -> None:
    attempted = tmp_path / "scope" / "frontend" / "missing.md"
    with pytest.raises(FileNotFoundError, match=str(attempted)):
        resolve_lane_path(tmp_path, "frontend/missing", Tier.SCOPE)


async def test_lane_filter_and_dispatch_are_applied_in_one_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    reg = registry(("slop-hygiene", Tier.BASE), ("dynamic/goal-parity", Tier.DYNAMIC))
    runtime = FakeRuntime()
    dispatch_calls = 0
    dispatch_concurrency: list[int] = []
    original_dispatch = discover_module.dispatch_outcome

    async def counting_dispatch(
        runs: Sequence[PlannedRun],
        dispatch_runtime: Runtime,
        *,
        out_root: Path,
        concurrency: int = 8,
        deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
        on_progress: Callable[[RunResult], None] | None = None,
        host_gate: HostSlotGate | None = None,
        prior_valid_lane_chunks: set[tuple[str, int]] | None = None,
        prior_retry_lane_chunks: set[tuple[str, int]] | None = None,
        attempt_numbers_by_key: dict[tuple[str, int, int], int] | None = None,
        resume_retry_feedback_by_lane_chunk: dict[tuple[str, int], str] | None = None,
    ) -> DispatchOutcome:
        nonlocal dispatch_calls
        dispatch_calls += 1
        dispatch_concurrency.append(concurrency)
        return await original_dispatch(
            runs,
            dispatch_runtime,
            out_root=out_root,
            concurrency=concurrency,
            deadline_seconds=deadline_seconds,
            on_progress=on_progress,
            host_gate=host_gate,
            prior_valid_lane_chunks=prior_valid_lane_chunks,
            prior_retry_lane_chunks=prior_retry_lane_chunks,
            attempt_numbers_by_key=attempt_numbers_by_key,
            resume_retry_feedback_by_lane_chunk=resume_retry_feedback_by_lane_chunk,
        )

    monkeypatch.setattr(discover_module, "dispatch_outcome", counting_dispatch)

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=2,
        concurrency=3,
        lane_filter=["slop-hygiene"],
    )

    assert dispatch_calls == 1
    assert dispatch_concurrency == [3]
    assert set(result.lane_results) == {"slop-hygiene"}
    assert runtime.calls == [("slop-hygiene", 1), ("slop-hygiene", 2)]


async def test_discover_reuses_manifest_bound_valid_results_without_dispatching_them(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    reused = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        completed_results={("slop-hygiene", 1, 1): reused},
    )

    assert runtime.calls == []
    assert result.coverage[0].valid == 1
    assert [attempt.model_dump() for attempt in result.coverage[0].runs[0].attempts] == [
        {"attempt": 1, "valid": True, "invalid_reason": None}
    ]


async def test_discover_resume_restores_a_correctable_failure_as_the_replacement_wave(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    prior = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    reused = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    assert remaining_discovery_plan(plan, {}).initial_runs == 1
    assert remaining_discovery_plan(plan, {("slop-hygiene", 1, 1): reused}).initial_runs == 0
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={("slop-hygiene", 1, 1): [prior]},
    )

    assert runtime.run_dirs == [tmp_path / "out" / "slop-hygiene" / "retry" / "r1"]
    assert "schema_validation_error" in runtime.prompts[0][1]
    assert [attempt.model_dump() for attempt in result.coverage[0].runs[0].attempts] == [
        {"attempt": 1, "valid": False, "invalid_reason": "schema_validation_error"},
        {"attempt": 2, "valid": True, "invalid_reason": None},
    ]


async def test_discover_resume_does_not_start_a_third_attempt_after_replacement(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    prior = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    runtime = FakeRuntime(
        statuses={"slop-hygiene": [RunStatus.INVALID]},
        invalid_reasons={"slop-hygiene": ["schema_validation_error"]},
    )

    with pytest.raises(IncompleteDiscoveryError, match="slop-hygiene"):
        await discover(
            registry=reg,
            lanes_root=lanes_root,
            target=target(),
            runtime=runtime,
            out_root=tmp_path / "out",
            planned=plan,
            prior_attempts={("slop-hygiene", 1, 1): [prior]},
        )

    assert runtime.run_dirs == [tmp_path / "out" / "slop-hygiene" / "retry" / "r1"]


async def test_discover_resume_completes_partial_initial_wave_before_one_replacement(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=2,
    )
    prior = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    runtime = FakeRuntime(
        statuses={
            "slop-hygiene": [RunStatus.INVALID, RunStatus.VALID, RunStatus.VALID],
        },
        invalid_reasons={"slop-hygiene": ["schema_validation_error"]},
    )

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={
            ("slop-hygiene", 1, 1): [prior],
        },
    )

    assert runtime.run_dirs == [
        tmp_path / "out" / "slop-hygiene" / "r2",
        tmp_path / "out" / "slop-hygiene" / "retry" / "r1",
        tmp_path / "out" / "slop-hygiene" / "retry" / "r2",
    ]
    assert [[attempt.valid for attempt in run.attempts] for run in result.coverage[0].runs] == [
        [False, True],
        [False, True],
    ]


async def test_discover_resume_does_not_replace_when_a_sibling_is_already_valid(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=2,
    )
    valid_prior = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    invalid_prior = RunResult(
        lane_id="slop-hygiene",
        replica=2,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r2",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={
            ("slop-hygiene", 1, 1): [valid_prior],
            ("slop-hygiene", 2, 1): [invalid_prior],
        },
    )

    assert runtime.calls == []
    assert result.coverage[0].valid == 1
    assert [run.valid for run in result.coverage[0].runs] == [True, False]


async def test_discover_resume_completes_only_missing_replacement_replicas(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=2,
    )
    initial_one = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    replacement_one = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "retry" / "r1",
    )
    initial_two = RunResult(
        lane_id="slop-hygiene",
        replica=2,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r2",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={
            ("slop-hygiene", 1, 1): [initial_one, replacement_one],
            ("slop-hygiene", 2, 1): [initial_two],
        },
        prior_retry_keys={("slop-hygiene", 1, 1)},
    )

    assert runtime.run_dirs == [tmp_path / "out" / "slop-hygiene" / "retry" / "r2"]
    assert [[attempt.valid for attempt in run.attempts] for run in result.coverage[0].runs] == [
        [False, False],
        [False, True],
    ]


async def test_discover_resume_does_not_complete_partial_retry_without_all_invalid_initials(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=2,
    )
    initial_one = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="exit_nonzero:1",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    replacement_one = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "retry" / "r1",
    )
    correctable_initial_two = RunResult(
        lane_id="slop-hygiene",
        replica=2,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r2",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={
            ("slop-hygiene", 1, 1): [initial_one, replacement_one],
            ("slop-hygiene", 2, 1): [correctable_initial_two],
        },
        prior_retry_keys={("slop-hygiene", 1, 1)},
    )

    assert runtime.calls == []
    assert result.coverage[0].valid == 1


async def test_discover_does_not_start_a_third_attempt_without_retry_metadata(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    initial = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    replacement = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "retry" / "r1",
    )
    runtime = FakeRuntime()

    with pytest.raises(IncompleteDiscoveryError, match="slop-hygiene"):
        await discover(
            registry=reg,
            lanes_root=lanes_root,
            target=target(),
            runtime=runtime,
            out_root=tmp_path / "out",
            planned=plan,
            prior_attempts={("slop-hygiene", 1, 1): [initial, replacement]},
        )

    assert runtime.calls == []


async def test_discover_accepts_legacy_retry_lane_chunk_state(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    prior = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    runtime = FakeRuntime()

    with pytest.raises(IncompleteDiscoveryError, match="slop-hygiene"):
        await discover(
            registry=reg,
            lanes_root=lanes_root,
            target=target(),
            runtime=runtime,
            out_root=tmp_path / "out",
            planned=plan,
            prior_attempts={("slop-hygiene", 1, 1): [prior]},
            prior_retry_lane_chunks={("slop-hygiene", 1)},
        )

    assert runtime.calls == []


async def test_discover_resume_ignores_history_outside_the_rebuilt_plan(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    reg = registry(("slop-hygiene", Tier.BASE))
    plan = plan_discovery(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        replicas=1,
    )
    planned_valid = RunResult(
        lane_id="slop-hygiene",
        replica=1,
        status=RunStatus.VALID,
        output=RuntimeLaneOutput(verdict="PASS", findings=[]),
        invalid_reason=None,
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r1",
    )
    stale_invalid = RunResult(
        lane_id="slop-hygiene",
        replica=2,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason="schema_validation_error",
        wall_seconds=0,
        artifact_dir=tmp_path / "prior" / "r2",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        planned=plan,
        prior_attempts={
            ("slop-hygiene", 1, 1): [planned_valid],
            ("slop-hygiene", 2, 1): [stale_invalid],
        },
    )

    assert runtime.calls == []
    assert [run.replica for run in result.coverage[0].runs] == [1]
    assert result.coverage[0].valid == 1


async def test_pr_brief_fallback_and_operator_brief_wins(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    reg = registry(("dynamic/goal-parity", Tier.DYNAMIC))

    fallback_runtime = FakeRuntime()
    await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(pr=True),
        runtime=fallback_runtime,
        out_root=tmp_path / "fallback",
        replicas=1,
    )
    fallback_prompt = fallback_runtime.prompts[0][1]
    assert "Add a thing\n\nIt should stay correct." in fallback_prompt
    assert "UNVERIFIED claim of intent" in fallback_prompt

    operator_runtime = FakeRuntime()
    await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(pr=True),
        runtime=operator_runtime,
        out_root=tmp_path / "operator",
        brief="Operator-authored intent",
        brief_source="pr_body",
        replicas=1,
    )
    operator_prompt = operator_runtime.prompts[0][1]
    assert "Operator-authored intent" in operator_prompt
    assert "Add a thing" not in operator_prompt
    assert "UNVERIFIED claim of intent" not in operator_prompt


async def test_required_dynamic_brief_is_skipped_without_a_runtime_call(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    path = write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "rules:\n", "requires_brief: true\nscope: diff\nrules:\n"
        ),
        encoding="utf-8",
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=registry(("dynamic/goal-parity", Tier.DYNAMIC)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
    )

    assert runtime.calls == []
    coverage = result.coverage[0]
    assert coverage.dispatched == 0
    assert coverage.skipped_reason == "brief_unavailable"


async def test_enrichment_computes_hunks_anchors_and_off_diff_fallback(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    raw_findings = [
        RuntimeFinding(
            rule_id="base-review/rule",
            file="src/a.py",
            line=1,
            severity=Severity.WARNING,
            body="Anchored issue",
        ),
        RuntimeFinding(
            rule_id="base-review/rule",
            file="elsewhere.py",
            line=99,
            severity=Severity.SUGGESTION,
            body="Off-diff issue",
        ),
    ]
    runtime = FakeRuntime(findings={"base-review": raw_findings})

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
    )

    anchored, off_diff = result.findings
    assert anchored.lane_id == "base-review"
    assert anchored.replica == 1
    assert anchored.hunk_id == "src/a.py@@-0,0+1,2@@"
    assert anchored.anchorable is True
    assert anchored.line == 1
    assert off_diff.hunk_id == "elsewhere.py:*"
    assert off_diff.anchorable is False
    assert off_diff.line == 99


async def test_coverage_keeps_all_invalid_lane(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "good", Tier.BASE)
    write_lane(lanes_root, "bad", Tier.BASE)
    runtime = FakeRuntime(invalid_lanes={"bad"})

    with pytest.raises(IncompleteDiscoveryError, match="bad"):
        await discover(
            registry=registry(("good", Tier.BASE), ("bad", Tier.BASE)),
            lanes_root=lanes_root,
            target=target(),
            runtime=runtime,
            out_root=tmp_path / "out",
            replicas=2,
        )

    assert len(runtime.calls) == 4  # two good + two non-correctable invalid bad


async def test_retried_coverage_preserves_ordered_attempt_status_and_reason(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "recovers", Tier.BASE)
    runtime = FakeRuntime(
        statuses={"recovers": [RunStatus.INVALID, RunStatus.VALID]},
        invalid_reasons={"recovers": ["schema_validation_error"]},
    )

    result = await discover(
        registry=registry(("recovers", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
    )

    run = result.coverage[0].runs[0]
    assert run.valid is True
    assert run.invalid_reason is None
    assert [attempt.model_dump() for attempt in run.attempts] == [
        {"attempt": 1, "valid": False, "invalid_reason": "schema_validation_error"},
        {"attempt": 2, "valid": True, "invalid_reason": None},
    ]


async def test_non_retried_coverage_has_one_attempt_mirroring_row(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "steady", Tier.BASE)

    result = await discover(
        registry=registry(("steady", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=FakeRuntime(),
        out_root=tmp_path / "out",
    )

    run = result.coverage[0].runs[0]
    assert [attempt.model_dump() for attempt in run.attempts] == [
        {
            "attempt": 1,
            "valid": run.valid,
            "invalid_reason": run.invalid_reason,
        }
    ]


@pytest.mark.parametrize(
    "attempts",
    [
        [
            {"attempt": 2, "valid": False, "invalid_reason": "exit_nonzero:124"},
            {"attempt": 3, "valid": True, "invalid_reason": None},
        ],
        [{"attempt": 1, "valid": False, "invalid_reason": "exit_nonzero:124"}],
    ],
)
def test_run_coverage_rejects_non_sequential_or_finally_mismatched_attempts(
    attempts: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError):
        RunCoverage(
            replica=1,
            chunk=1,
            valid=True,
            findings=0,
            invalid_reason=None,
            attempts=attempts,
        )


def test_run_coverage_accepts_attempts_and_final_diagnostic_together() -> None:
    diagnostic = RunDiagnostic(
        exit_code=124,
        log_path="/tmp/lane/r1/run.log",
        log_bytes=17,
        output_path="/tmp/lane/r1/out.json",
        output_bytes=0,
    )

    coverage = RunCoverage(
        replica=1,
        chunk=1,
        valid=False,
        findings=0,
        invalid_reason="empty",
        attempts=[
            {"attempt": 1, "valid": False, "invalid_reason": "exit_nonzero:124"},
            {"attempt": 2, "valid": False, "invalid_reason": "empty"},
        ],
        diagnostic=diagnostic,
    )

    assert coverage.attempts[0].invalid_reason == "exit_nonzero:124"
    assert coverage.diagnostic == diagnostic


def test_run_coverage_rejects_valid_run_with_diagnostic() -> None:
    with pytest.raises(ValueError, match=r"valid.*diagnostic"):
        RunCoverage(
            replica=1,
            chunk=1,
            valid=True,
            findings=0,
            invalid_reason=None,
            attempts=[{"attempt": 1, "valid": True, "invalid_reason": None}],
            diagnostic=RunDiagnostic(exit_code=0),
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"attempt": 0, "valid": True, "invalid_reason": None},
        {"attempt": 1, "valid": True, "invalid_reason": "unexpected"},
        {"attempt": 1, "valid": False, "invalid_reason": None},
        {"attempt": 1, "valid": False, "invalid_reason": "   "},
        {"attempt": 1, "valid": True, "invalid_reason": None, "extra": "forbidden"},
    ],
)
def test_run_attempt_is_strict_and_enforces_validity_reason_invariant(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        discover_module.RunAttempt.model_validate(raw)


async def test_diff_budget_filters_prompt_but_keeps_full_changed_paths(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    source_diff = target().diff
    generated_path = "runtime-snapshots/contract-graph.json"
    generated_diff = (
        f"diff --git a/{generated_path} b/{generated_path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{generated_path}\n"
        "@@ -0,0 +1 @@\n"
        "+generated\n"
    )
    budget_target = target().model_copy(
        update={
            "changed_paths": ["src/a.py", generated_path],
            "diff": generated_diff + source_diff,
        }
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=budget_target,
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
    )

    prompt = runtime.prompts[0][1]
    assert source_diff in prompt
    assert generated_diff not in prompt
    assert "# rvw: 1 files excluded from review diff" in prompt
    assert budget_target.changed_paths == ["src/a.py", generated_path]
    assert result.budget is not None
    assert result.budget.kept_files == ["src/a.py"]
    assert result.budget.excluded_reason == {generated_path: "generated-path"}


async def test_all_excluded_diff_fails_before_discovery_dispatch(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    generated_path = "runtime-snapshots/contract-graph.json"
    generated_target = target().model_copy(
        update={
            "changed_paths": [generated_path],
            "diff": (
                f"diff --git a/{generated_path} b/{generated_path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{generated_path}\n"
                "@@ -0,0 +1 @@\n"
                "+generated\n"
            ),
        }
    )
    runtime = FakeRuntime()

    with pytest.raises(
        EmptyReviewDiffError,
        match=r"^target produced an empty review diff; excluded: ",
    ) as caught:
        await discover(
            registry=registry(("base-review", Tier.BASE)),
            lanes_root=lanes_root,
            target=generated_target,
            runtime=runtime,
            out_root=tmp_path / "out",
            replicas=1,
        )

    assert caught.value.error_code == "empty-review-diff"
    assert caught.value.excluded_reason == {generated_path: "generated-path"}
    assert runtime.calls == []
    assert runtime.prompts == []


def multi_chunk_target() -> ResolvedTarget:
    paths = [f"src/chunk-{index}.py" for index in range(3)]
    segments = [
        (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            f"+{'x' * 149_900}\n"
        )
        for path in paths
    ]
    return target().model_copy(update={"changed_paths": paths, "diff": "".join(segments)})


async def test_chunk_prompts_fan_out_with_file_plan_and_artifact_axis(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    runtime = FakeRuntime()

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=multi_chunk_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
    )

    assert result.budget is not None
    assert result.budget.chunk_count == 2
    assert runtime.run_dirs == [
        tmp_path / "out" / "base-review" / "c1" / "r1",
        tmp_path / "out" / "base-review" / "c2" / "r1",
    ]
    assert len(runtime.prompts) == 2
    first_prompt = runtime.prompts[0][1]
    second_prompt = runtime.prompts[1][1]
    for prompt, marker in ((first_prompt, "chunk 1/2"), (second_prompt, "chunk 2/2")):
        assert marker in prompt
        assert "src/chunk-0.py" in prompt
        assert "src/chunk-1.py" in prompt
        assert "src/chunk-2.py" in prompt
    assert "[included] src/chunk-0.py" in first_prompt
    assert "[included] src/chunk-1.py" in first_prompt
    assert "[other] src/chunk-2.py" in first_prompt
    assert "diff --git a/src/chunk-2.py" not in first_prompt
    assert "[other] src/chunk-0.py" in second_prompt
    assert "[included] src/chunk-2.py" in second_prompt
    assert "diff --git a/src/chunk-0.py" not in second_prompt
    coverage = result.coverage[0]
    assert coverage.dispatched == 2
    assert coverage.valid == 2
    assert [(run.replica, run.chunk, run.valid) for run in coverage.runs] == [
        (1, 1, True),
        (1, 2, True),
    ]


async def test_stable_finding_id_does_not_depend_on_chunk_plan(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    finding = RuntimeFinding(
        rule_id="base-review/rule",
        file="src/chunk-0.py",
        line=1,
        severity=Severity.WARNING,
        body="same site",
    )
    one_chunk_target = multi_chunk_target().model_copy(
        update={
            "changed_paths": ["src/chunk-0.py"],
            "diff": multi_chunk_target().diff.split("diff --git a/src/chunk-1.py", maxsplit=1)[0],
        }
    )

    one = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=one_chunk_target,
        runtime=FakeRuntime(findings={"base-review": [finding]}),
        out_root=tmp_path / "one",
        replicas=1,
    )
    many = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=multi_chunk_target(),
        runtime=FakeRuntime(findings={"base-review": [finding]}),
        out_root=tmp_path / "many",
        replicas=1,
    )

    one_group = merge(one.findings, lane_tiers={"base-review": Tier.BASE}).groups[0]
    many_group = merge(many.findings, lane_tiers={"base-review": Tier.BASE}).groups[0]
    assert one_group.key == many_group.key
