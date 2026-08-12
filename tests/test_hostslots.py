from __future__ import annotations

import asyncio
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import rvw.hostslots as hostslots_module
from rvw.hostslots import HostSlotGate, host_slot_gate_from_env, parse_host_concurrency

_HOLDER_SCRIPT = """
import asyncio
import sys
from pathlib import Path

from rvw.hostslots import HostSlotGate


async def main() -> None:
    async with HostSlotGate(1, base_dir=Path(sys.argv[1])).slot():
        Path(sys.argv[2]).write_text("ready", encoding="utf-8")
        await asyncio.Event().wait()


asyncio.run(main())
"""


def _start_slot_holder(base_dir: Path, ready_path: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SCRIPT, str(base_dir), str(ready_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if ready_path.exists():
            return process
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"slot holder exited before readiness: {stdout=} {stderr=}")
        time.sleep(0.01)
    process.kill()
    process.wait(timeout=3)
    pytest.fail("slot holder did not signal readiness")


def _try_nonblocking_slot(slot_path: Path) -> int | None:
    descriptor = os.open(slot_path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor


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


def test_relative_xdg_runtime_dir_falls_back_to_absolute_slot_root() -> None:
    gate = host_slot_gate_from_env({"XDG_RUNTIME_DIR": "run"})
    assert gate is not None
    assert gate.base_dir == Path("/tmp/rvw-slots")
    assert gate.base_dir.is_absolute()


def test_absolute_xdg_runtime_dir_selects_runtime_slot_root(tmp_path: Path) -> None:
    gate = host_slot_gate_from_env({"XDG_RUNTIME_DIR": str(tmp_path)})
    assert gate is not None
    assert gate.base_dir == tmp_path / "rvw-slots"


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


async def test_contended_cancellation_uses_no_blocking_executor_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    holder = HostSlotGate(1, base_dir=tmp_path)
    waiter = HostSlotGate(1, base_dir=tmp_path)
    to_thread_calls = 0

    async def recording_to_thread(*args: object, **kwargs: object) -> object:
        nonlocal to_thread_calls
        del args, kwargs
        to_thread_calls += 1
        await asyncio.sleep(0)
        raise AssertionError("host-slot acquisition must not use asyncio.to_thread")

    async with holder.slot():
        monkeypatch.setattr(hostslots_module.asyncio, "to_thread", recording_to_thread)
        task = asyncio.create_task(waiter._acquire())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.1)
        assert to_thread_calls == 0

    async with asyncio.timeout(1), HostSlotGate(1, base_dir=tmp_path).slot():
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


def test_live_process_holder_blocks_nonblocking_acquisition(tmp_path: Path) -> None:
    ready_path = tmp_path / "holder-ready"
    process = _start_slot_holder(tmp_path, ready_path)
    try:
        assert _try_nonblocking_slot(tmp_path / "c1" / "slot-00") is None
    finally:
        process.kill()
        process.wait(timeout=3)


def test_sigkill_releases_cross_process_slot(tmp_path: Path) -> None:
    ready_path = tmp_path / "holder-ready"
    process = _start_slot_holder(tmp_path, ready_path)
    try:
        assert _try_nonblocking_slot(tmp_path / "c1" / "slot-00") is None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)

    descriptor: int | None = None
    deadline = time.monotonic() + 3
    while descriptor is None and time.monotonic() < deadline:
        descriptor = _try_nonblocking_slot(tmp_path / "c1" / "slot-00")
        if descriptor is None:
            time.sleep(0.01)

    assert descriptor is not None
    os.close(descriptor)


async def test_preexisting_slot_directories_are_enforced_to_mode_0700(tmp_path: Path) -> None:
    slot_root = tmp_path / "slots"
    slot_dir = slot_root / "c1"
    slot_dir.mkdir(parents=True)
    slot_root.chmod(0o777)
    slot_dir.chmod(0o775)

    async with HostSlotGate(1, base_dir=slot_root).slot():
        assert slot_root.stat().st_mode & 0o777 == 0o700
        assert slot_dir.stat().st_mode & 0o777 == 0o700


async def test_xdg_runtime_parent_permissions_are_not_changed(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o755)
    runtime_dir.chmod(0o755)

    gate = HostSlotGate(1, environ={"XDG_RUNTIME_DIR": str(runtime_dir)})
    async with gate.slot():
        assert runtime_dir.stat().st_mode & 0o777 == 0o755
        assert (runtime_dir / "rvw-slots").stat().st_mode & 0o777 == 0o700
        assert (runtime_dir / "rvw-slots" / "c1").stat().st_mode & 0o777 == 0o700

    assert runtime_dir.stat().st_mode & 0o777 == 0o755


async def test_slot_file_is_opened_relative_to_validated_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_open = os.open
    slot_opens: list[tuple[object, int | None]] = []

    def recording_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(path).name.startswith("slot-"):
            slot_opens.append((path, dir_fd))
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", recording_open)

    async with HostSlotGate(1, base_dir=tmp_path).slot():
        pass

    assert slot_opens
    assert all(path == "slot-00" and dir_fd is not None for path, dir_fd in slot_opens)


def test_gate_construction_requires_o_nofollow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delattr(os, "O_NOFOLLOW")

    with pytest.raises(RuntimeError, match="O_NOFOLLOW"):
        HostSlotGate(1, base_dir=tmp_path)
