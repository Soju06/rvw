"""Single-wave, longest-processing-time-first run dispatcher."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from rvw.lane import Lane
from rvw.runtimes import RunResult, RunStatus, Runtime

_COST_ORDER = {"heavy": 0, "normal": 1, "light": 2}
DEFAULT_CONCURRENCY = 8


def lpt_sort_key(lane_cost: str) -> int:
    """Return the shared longest-processing-time-first key for a lane cost."""

    return _COST_ORDER[lane_cost]


@dataclass(frozen=True, slots=True)
class PlannedRun:
    lane: Lane
    prompt: str
    replica: int
    chunk: int = 1
    chunk_count: int = 1

    def __post_init__(self) -> None:
        if self.replica < 1:
            raise ValueError("replica must be at least 1")
        if self.chunk < 1:
            raise ValueError("chunk must be at least 1")
        if self.chunk_count < 1 or self.chunk > self.chunk_count:
            raise ValueError("chunk must be within chunk_count")


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    """Final run results and shadowed initial results for retried identities."""

    results: list[RunResult]
    initial_by_key: dict[tuple[str, int, int], RunResult]


async def dispatch_outcome(
    runs: Sequence[PlannedRun],
    runtime: Runtime,
    *,
    out_root: Path,
    concurrency: int = DEFAULT_CONCURRENCY,
    deadline_seconds: int = 600,
    on_progress: Callable[[RunResult], None] | None = None,
) -> DispatchOutcome:
    """Dispatch runs and retain initial results shadowed by the retry wave."""

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def execute_one(run: PlannedRun, *, retry: bool = False) -> RunResult:
        async with semaphore:
            lane_slug = run.lane.id.replace("/", "--")
            lane_dir = out_root / lane_slug
            if run.chunk_count > 1:
                lane_dir /= f"c{run.chunk}"
            if retry:
                lane_dir /= "retry"
            run_dir = lane_dir / f"r{run.replica}"
            run_dir.mkdir(parents=True, exist_ok=True)
            result = replace(
                await runtime.execute(
                    lane=run.lane,
                    prompt=run.prompt,
                    run_dir=run_dir,
                    deadline_seconds=deadline_seconds,
                ),
                chunk=run.chunk,
            )
            if on_progress is not None:
                on_progress(result)
            return result

    async def execute_wave(
        wave_runs: Sequence[PlannedRun], *, retry: bool = False
    ) -> list[RunResult]:
        ordered = sorted(wave_runs, key=lambda run: lpt_sort_key(run.lane.cost))
        tasks = [asyncio.create_task(execute_one(run, retry=retry)) for run in ordered]
        return list(await asyncio.gather(*tasks))

    main_results = await execute_wave(runs)
    results_by_lane_chunk: dict[tuple[str, int], list[RunResult]] = {}
    for result in main_results:
        results_by_lane_chunk.setdefault((result.lane_id, result.chunk), []).append(result)

    retry_lane_chunks = {
        lane_chunk
        for lane_chunk, lane_results in results_by_lane_chunk.items()
        if all(result.status is RunStatus.INVALID for result in lane_results)
    }
    retry_runs = [run for run in runs if (run.lane.id, run.chunk) in retry_lane_chunks]
    retry_results = await execute_wave(retry_runs, retry=True)

    final_by_key = {
        (result.lane_id, result.replica, result.chunk): result
        for result in [*main_results, *retry_results]
    }
    final_results = sorted(
        final_by_key.values(), key=lambda result: (result.lane_id, result.chunk, result.replica)
    )
    initial_by_key = {
        (result.lane_id, result.replica, result.chunk): result
        for result in main_results
        if (result.lane_id, result.chunk) in retry_lane_chunks
    }
    return DispatchOutcome(results=final_results, initial_by_key=initial_by_key)


async def dispatch(
    runs: Sequence[PlannedRun],
    runtime: Runtime,
    *,
    out_root: Path,
    concurrency: int = DEFAULT_CONCURRENCY,
    deadline_seconds: int = 600,
    on_progress: Callable[[RunResult], None] | None = None,
) -> list[RunResult]:
    """Dispatch all planned runs and return only each identity's final result."""

    outcome = await dispatch_outcome(
        runs,
        runtime,
        out_root=out_root,
        concurrency=concurrency,
        deadline_seconds=deadline_seconds,
        on_progress=on_progress,
    )
    return outcome.results


__all__: list[str] = [
    "DEFAULT_CONCURRENCY",
    "DispatchOutcome",
    "PlannedRun",
    "dispatch",
    "dispatch_outcome",
    "lpt_sort_key",
]
