"""Bounded retry, longest-processing-time-first run dispatcher."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from rvw.hostslots import HostSlotGate, host_slot
from rvw.lane import Lane
from rvw.prompts import build_retry_feedback
from rvw.runtimes import RunResult, RunStatus, Runtime, is_correctable_invalid_reason

_COST_ORDER = {"heavy": 0, "normal": 1, "light": 2}
DEFAULT_CONCURRENCY = 8
DEFAULT_DEADLINE_SECONDS = 600
MAX_DEADLINE_SECONDS = 1800


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
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    on_progress: Callable[[RunResult], None] | None = None,
    host_gate: HostSlotGate | None = None,
    prior_valid_lane_chunks: set[tuple[str, int]] | None = None,
    prior_retry_lane_chunks: set[tuple[str, int]] | None = None,
    attempt_numbers_by_key: Mapping[tuple[str, int, int], int] | None = None,
    resume_retry_feedback_by_lane_chunk: Mapping[tuple[str, int], str] | None = None,
) -> DispatchOutcome:
    """Dispatch runs and retain initial results shadowed by the retry wave."""

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def execute_one(
        run: PlannedRun,
        *,
        retry_feedback: str | None = None,
        attempt_number: int = 1,
    ) -> RunResult:
        async with semaphore:
            lane_slug = run.lane.id.replace("/", "--")
            lane_dir = out_root / lane_slug
            if run.chunk_count > 1:
                lane_dir /= f"c{run.chunk}"
            if retry_feedback is not None:
                lane_dir /= "retry"
                if attempt_number > 2:
                    lane_dir /= f"a{attempt_number}"
            elif attempt_number > 1:
                lane_dir /= "resume"
                lane_dir /= f"a{attempt_number}"
            run_dir = lane_dir / f"r{run.replica}"
            run_dir.mkdir(parents=True, exist_ok=True)
            prompt = run.prompt if retry_feedback is None else f"{run.prompt}\n\n{retry_feedback}"
            async with host_slot(host_gate):
                result = replace(
                    await runtime.execute(
                        lane=run.lane,
                        prompt=prompt,
                        run_dir=run_dir,
                        deadline_seconds=deadline_seconds,
                    ),
                    chunk=run.chunk,
                )
            if on_progress is not None:
                on_progress(result)
            return result

    async def execute_wave(
        wave_runs: Sequence[PlannedRun],
        *,
        retry_feedback_by_lane_chunk: Mapping[tuple[str, int], str] | None = None,
        increment_retry_attempt: bool = True,
    ) -> list[RunResult]:
        ordered = sorted(wave_runs, key=lambda run: lpt_sort_key(run.lane.cost))
        tasks = [
            asyncio.create_task(
                execute_one(
                    run,
                    retry_feedback=(
                        None
                        if retry_feedback_by_lane_chunk is None
                        else retry_feedback_by_lane_chunk[(run.lane.id, run.chunk)]
                    ),
                    attempt_number=(
                        (attempt_numbers_by_key or {}).get((run.lane.id, run.replica, run.chunk), 1)
                        + (
                            1
                            if retry_feedback_by_lane_chunk is not None and increment_retry_attempt
                            else 0
                        )
                    ),
                )
            )
            for run in ordered
        ]
        return list(await asyncio.gather(*tasks))

    resume_retry_feedback = resume_retry_feedback_by_lane_chunk or {}
    resume_retry_lane_chunks = set(resume_retry_feedback)
    main_runs = [run for run in runs if (run.lane.id, run.chunk) not in resume_retry_lane_chunks]
    resume_retry_runs = [
        run for run in runs if (run.lane.id, run.chunk) in resume_retry_lane_chunks
    ]
    main_results = await execute_wave(main_runs)
    resumed_retry_results = await execute_wave(
        resume_retry_runs,
        retry_feedback_by_lane_chunk=resume_retry_feedback,
        increment_retry_attempt=False,
    )
    results_by_lane_chunk: dict[tuple[str, int], list[RunResult]] = {}
    for result in main_results:
        results_by_lane_chunk.setdefault((result.lane_id, result.chunk), []).append(result)

    prior_valid = prior_valid_lane_chunks or set()
    prior_retry = (prior_retry_lane_chunks or set()) | resume_retry_lane_chunks
    retry_lane_chunks = {
        lane_chunk
        for lane_chunk, lane_results in results_by_lane_chunk.items()
        if lane_chunk not in prior_valid
        and lane_chunk not in prior_retry
        and all(result.status is RunStatus.INVALID for result in lane_results)
        and all(is_correctable_invalid_reason(result.invalid_reason) for result in lane_results)
    }
    retry_runs = [run for run in runs if (run.lane.id, run.chunk) in retry_lane_chunks]
    retry_feedback_by_lane_chunk = {
        lane_chunk: build_retry_feedback(
            [
                f"replica {result.replica}: {result.invalid_reason or 'unknown_invalid'}"
                for result in sorted(
                    results_by_lane_chunk[lane_chunk], key=lambda result: result.replica
                )
            ]
        )
        for lane_chunk in retry_lane_chunks
    }
    retry_results = await execute_wave(
        retry_runs,
        retry_feedback_by_lane_chunk=retry_feedback_by_lane_chunk,
    )

    final_by_key = {
        (result.lane_id, result.replica, result.chunk): result
        for result in [*main_results, *resumed_retry_results, *retry_results]
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
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    on_progress: Callable[[RunResult], None] | None = None,
    host_gate: HostSlotGate | None = None,
) -> list[RunResult]:
    """Dispatch all planned runs and return only each identity's final result."""

    outcome = await dispatch_outcome(
        runs,
        runtime,
        out_root=out_root,
        concurrency=concurrency,
        deadline_seconds=deadline_seconds,
        on_progress=on_progress,
        host_gate=host_gate,
    )
    return outcome.results


__all__: list[str] = [
    "DEFAULT_CONCURRENCY",
    "DEFAULT_DEADLINE_SECONDS",
    "MAX_DEADLINE_SECONDS",
    "DispatchOutcome",
    "PlannedRun",
    "dispatch",
    "dispatch_outcome",
    "lpt_sort_key",
]
