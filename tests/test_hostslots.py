from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from rvw.hostslots import HostSlotGate, host_slot_gate_from_env, parse_host_concurrency


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 12), ("0", 0), ("1", 1), ("24", 24)],
)
def test_parse_host_concurrency_accepts_default_disable_and_positive_caps(
    value: str | None,
    expected: int,
) -> None:
    assert parse_host_concurrency(value) == expected


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", ""])
def test_parse_host_concurrency_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="RVW_HOST_CONCURRENCY"):
        parse_host_concurrency(value)


def test_zero_host_concurrency_returns_disabled_gate(tmp_path: Path) -> None:
    slot_root = tmp_path / "slots"
    assert host_slot_gate_from_env({"RVW_HOST_CONCURRENCY": "0"}, base_dir=slot_root) is None
    assert not slot_root.exists()


async def test_two_gate_instances_contend_for_the_same_slot_root(tmp_path: Path) -> None:
    first = HostSlotGate(1, base_dir=tmp_path)
    second = HostSlotGate(1, base_dir=tmp_path)
    attempting = asyncio.Event()
    acquired = asyncio.Event()

    async def acquire_second() -> None:
        attempting.set()
        async with second.slot():
            acquired.set()

    async with first.slot():
        task = asyncio.create_task(acquire_second())
        await attempting.wait()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(acquired.wait()), timeout=0.05)

    await asyncio.wait_for(task, timeout=1)
    assert acquired.is_set()


async def test_slot_releases_on_success_exception_and_cancellation(tmp_path: Path) -> None:
    gate = HostSlotGate(1, base_dir=tmp_path)
    contender = HostSlotGate(1, base_dir=tmp_path)

    async with gate.slot():
        pass
    async with asyncio.timeout(1), contender.slot():
        pass

    with pytest.raises(RuntimeError, match="runtime failed"):
        async with gate.slot():
            raise RuntimeError("runtime failed")
    async with asyncio.timeout(1), contender.slot():
        pass

    entered = asyncio.Event()

    async def hold_until_cancelled() -> None:
        async with gate.slot():
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(hold_until_cancelled())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(1), contender.slot():
        pass


async def test_symlinked_slot_root_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    slot_root = tmp_path / "rvw-slots"
    slot_root.symlink_to(target, target_is_directory=True)

    gate = HostSlotGate(1, base_dir=slot_root)

    with pytest.raises(RuntimeError, match="symlink"):
        async with gate.slot():
            pass
