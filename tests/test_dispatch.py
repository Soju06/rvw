from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path

import rvw.dispatch as dispatch_module
from rvw.adjudicate import adjudicate
from rvw.discover import discover
from rvw.dispatch import PlannedRun, dispatch
from rvw.lane import Lane
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.sample import sample_lane
from rvw.schema import RuntimeLaneOutput
from rvw.stack_adjudicate import adjudicate_presence


def make_lane(lane_id: str, cost: str = "normal") -> Lane:
    return Lane.model_validate(
        {
            "lane": lane_id,
            "tier": "base",
            "cost": cost,
            "rules": [f"{lane_id}/rule"],
            "prompt_body": "Review the input.",
        }
    )


class FakeRuntime(Runtime):
    name = "fake"

    def __init__(
        self,
        *,
        statuses: dict[str, Sequence[RunStatus]] | None = None,
        delays: dict[str, float] | None = None,
    ) -> None:
        self._statuses = statuses or {}
        self._delays = delays or {}
        self._lane_call_counts: dict[str, int] = {}
        self.starts: list[tuple[str, int]] = []
        self.ends: list[tuple[str, int]] = []
        self.timings: list[tuple[str, int, float, float]] = []
        self.run_dirs: list[Path] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
    ) -> RunResult:
        del prompt, deadline_seconds
        replica = int(run_dir.name.removeprefix("r"))
        call_index = self._lane_call_counts.get(lane.id, 0)
        self._lane_call_counts[lane.id] = call_index + 1
        scripted = self._statuses.get(lane.id, ())
        status = scripted[call_index] if call_index < len(scripted) else RunStatus.VALID

        loop = asyncio.get_running_loop()
        started = loop.time()
        self.starts.append((lane.id, replica))
        self.run_dirs.append(run_dir)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self._delays.get(lane.id, 0.001))
        self.in_flight -= 1
        self.ends.append((lane.id, replica))
        self.timings.append((lane.id, replica, started, loop.time()))

        return RunResult(
            lane_id=lane.id,
            replica=replica,
            status=status,
            output=RuntimeLaneOutput(verdict="PASS") if status is RunStatus.VALID else None,
            invalid_reason="scripted_invalid" if status is RunStatus.INVALID else None,
            wall_seconds=self._delays.get(lane.id, 0.001),
            artifact_dir=run_dir,
        )

    def calls_for(self, lane_id: str) -> int:
        return self._lane_call_counts.get(lane_id, 0)


class ArtifactRuntime(FakeRuntime):
    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
    ) -> RunResult:
        marker = f"wave-{self.calls_for(lane.id) + 1}\n"
        for artifact_name in ("prompt.md", "run.log", "out.json"):
            (run_dir / artifact_name).write_text(marker, encoding="utf-8")
        return await super().execute(
            lane=lane,
            prompt=prompt,
            run_dir=run_dir,
            deadline_seconds=deadline_seconds,
        )


def planned(lane: Lane, replica: int = 1, *, chunk: int = 1, chunk_count: int = 1) -> PlannedRun:
    return PlannedRun(
        lane=lane,
        prompt="prompt",
        replica=replica,
        chunk=chunk,
        chunk_count=chunk_count,
    )


def test_runtime_concurrency_defaults_to_eight() -> None:
    for callable_ in (dispatch, discover, adjudicate, sample_lane, adjudicate_presence):
        assert inspect.signature(callable_).parameters["concurrency"].default == 8


async def test_heavy_runs_are_admitted_before_normal_and_light(tmp_path: Path) -> None:
    light = make_lane("light", "light")
    normal = make_lane("normal", "normal")
    heavy = make_lane("heavy", "heavy")
    runtime = FakeRuntime()

    await dispatch(
        [planned(light), planned(normal), planned(heavy)],
        runtime,
        out_root=tmp_path,
        concurrency=1,
    )

    by_start_time = sorted(runtime.timings, key=lambda timing: timing[2])
    assert [lane_id for lane_id, _replica, _start, _end in by_start_time] == [
        "heavy",
        "normal",
        "light",
    ]


async def test_max_in_flight_never_exceeds_concurrency(tmp_path: Path) -> None:
    lane = make_lane("bounded")
    runtime = FakeRuntime(delays={lane.id: 0.01})
    runs = [planned(lane, replica) for replica in range(1, 7)]

    await dispatch(runs, runtime, out_root=tmp_path, concurrency=2)

    assert runtime.max_in_flight == 2


async def test_one_invalid_replica_does_not_trigger_redispatch(tmp_path: Path) -> None:
    lane = make_lane("partly-valid")
    runtime = FakeRuntime(
        statuses={lane.id: [RunStatus.INVALID, RunStatus.VALID]},
    )

    results = await dispatch(
        [planned(lane, 1), planned(lane, 2)],
        runtime,
        out_root=tmp_path,
    )

    assert runtime.calls_for(lane.id) == 2
    assert [result.status for result in results] == [RunStatus.INVALID, RunStatus.VALID]


async def test_all_invalid_lane_is_redispatched_once(tmp_path: Path) -> None:
    lane = make_lane("recovers")
    runtime = FakeRuntime(
        statuses={
            lane.id: [
                RunStatus.INVALID,
                RunStatus.INVALID,
                RunStatus.VALID,
                RunStatus.VALID,
            ]
        }
    )

    results = await dispatch(
        [planned(lane, 1), planned(lane, 2)],
        runtime,
        out_root=tmp_path,
    )

    assert runtime.calls_for(lane.id) == 4
    assert all(result.status is RunStatus.VALID for result in results)


async def test_dispatch_outcome_exposes_initial_results_only_for_retried_keys(
    tmp_path: Path,
) -> None:
    recovers = make_lane("recovers")
    steady = make_lane("steady")
    runtime = FakeRuntime(
        statuses={
            recovers.id: [RunStatus.INVALID, RunStatus.VALID],
            steady.id: [RunStatus.VALID],
        }
    )
    outcome = await dispatch_module.dispatch_outcome(
        [planned(recovers), planned(steady)],
        runtime,
        out_root=tmp_path,
    )

    assert [result.status for result in outcome.results] == [
        RunStatus.VALID,
        RunStatus.VALID,
    ]
    assert set(outcome.initial_by_key) == {(recovers.id, 1, 1)}
    assert outcome.initial_by_key[(recovers.id, 1, 1)].status is RunStatus.INVALID


async def test_all_invalid_retry_preserves_initial_wave_artifacts(tmp_path: Path) -> None:
    lane = make_lane("preserve-invalid")
    runtime = ArtifactRuntime(
        statuses={lane.id: [RunStatus.INVALID, RunStatus.VALID]},
    )

    await dispatch([planned(lane)], runtime, out_root=tmp_path)

    initial_dir = tmp_path / lane.id / "r1"
    retry_dir = tmp_path / lane.id / "retry" / "r1"
    for artifact_name in ("prompt.md", "run.log", "out.json"):
        assert (initial_dir / artifact_name).read_text(encoding="utf-8") == "wave-1\n"
        assert (retry_dir / artifact_name).read_text(encoding="utf-8") == "wave-2\n"


async def test_still_invalid_after_retry_is_returned_without_looping(tmp_path: Path) -> None:
    lane = make_lane("never-valid")
    runtime = FakeRuntime(statuses={lane.id: [RunStatus.INVALID] * 4})

    results = await dispatch(
        [planned(lane, 1), planned(lane, 2)],
        runtime,
        out_root=tmp_path,
    )

    assert runtime.calls_for(lane.id) == 4
    assert all(result.status is RunStatus.INVALID for result in results)


async def test_results_are_sorted_and_progress_includes_retries(tmp_path: Path) -> None:
    lane_z = make_lane("z-lane")
    lane_a = make_lane("a-lane")
    runtime = FakeRuntime(statuses={lane_z.id: [RunStatus.INVALID] * 4})
    progress: list[tuple[str, int]] = []

    def on_progress(result: RunResult) -> None:
        progress.append((result.lane_id, result.replica))

    results = await dispatch(
        [planned(lane_z, 2), planned(lane_a, 1), planned(lane_z, 1)],
        runtime,
        out_root=tmp_path,
        on_progress=on_progress,
    )

    assert [(result.lane_id, result.replica) for result in results] == [
        ("a-lane", 1),
        ("z-lane", 1),
        ("z-lane", 2),
    ]
    assert len(progress) == 5


async def test_run_directory_slugs_lane_id(tmp_path: Path) -> None:
    lane = make_lane("scope/bori/agent")
    runtime = FakeRuntime()

    await dispatch([planned(lane, 3)], runtime, out_root=tmp_path)

    assert runtime.run_dirs == [tmp_path / "scope--bori--agent" / "r3"]


async def test_multi_chunk_paths_and_result_keys_are_distinct(tmp_path: Path) -> None:
    lane = make_lane("scope/bori/agent")
    runtime = FakeRuntime()

    results = await dispatch(
        [
            planned(lane, 1, chunk=1, chunk_count=2),
            planned(lane, 1, chunk=2, chunk_count=2),
        ],
        runtime,
        out_root=tmp_path,
    )

    assert runtime.run_dirs == [
        tmp_path / "scope--bori--agent" / "c1" / "r1",
        tmp_path / "scope--bori--agent" / "c2" / "r1",
    ]
    assert [(result.replica, result.chunk) for result in results] == [(1, 1), (1, 2)]


async def test_all_invalid_retry_is_scoped_to_lane_chunk(tmp_path: Path) -> None:
    lane = make_lane("chunk-retry")
    runtime = FakeRuntime(statuses={lane.id: [RunStatus.INVALID, RunStatus.VALID, RunStatus.VALID]})

    results = await dispatch(
        [
            planned(lane, 1, chunk=1, chunk_count=2),
            planned(lane, 1, chunk=2, chunk_count=2),
        ],
        runtime,
        out_root=tmp_path,
    )

    assert runtime.calls_for(lane.id) == 3
    assert [(result.chunk, result.status) for result in results] == [
        (1, RunStatus.VALID),
        (2, RunStatus.VALID),
    ]


def assert_runtime_protocol(runtime: Runtime, callback: Callable[[RunResult], None]) -> None:
    del runtime, callback


assert_runtime_protocol(FakeRuntime(), lambda _result: None)
