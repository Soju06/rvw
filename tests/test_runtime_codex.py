from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import rvw.runtimes.codex as codex_module
from rvw.lane import Lane, load_lane
from rvw.runtimes import RunStatus
from rvw.runtimes.codex import CodexRuntime

FIXTURE = Path(__file__).parent / "fixtures" / "lanes" / "slop-hygiene.md"

_SLEEP_CHILD_SCRIPT = """
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(f"{os.getppid()} {os.getpid()}", encoding="utf-8")
time.sleep(60)
"""
_SPAWN_PARENT_SCRIPT = f"""
import asyncio
import sys
from pathlib import Path

from rvw.runtimes.codex import _spawn


async def main() -> None:
    command = [
        "timeout",
        "--foreground",
        "--signal=TERM",
        "60s",
        sys.executable,
        "-c",
        {_SLEEP_CHILD_SCRIPT!r},
        sys.argv[1],
    ]
    await _spawn(command, "", Path(sys.argv[2]))


asyncio.run(main())
"""


def _linux_process_is_running(pid: int) -> bool:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return stat_text.rsplit(") ", maxsplit=1)[1][0] != "Z"


def valid_payload() -> dict[str, object]:
    return {"verdict": "PASS", "findings": []}


def install_spawn(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_dir: Path,
    exit_code: int = 0,
    payload: object | None = None,
    log_text: str = "tokens used: 42\n",
) -> list[tuple[list[str], Path | None]]:
    calls: list[tuple[list[str], Path | None]] = []

    async def fake_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        assert stdin_text
        calls.append((cmd, cwd))
        log_path.write_text(log_text, encoding="utf-8")
        if payload is not None:
            (run_dir / "out.json").write_text(json.dumps(payload), encoding="utf-8")
        return exit_code

    monkeypatch.setattr(codex_module, "_spawn", fake_spawn)
    return calls


async def execute_fixture(lane: Lane, run_dir: Path, prompt: str = "Review this tiny diff."):
    return await CodexRuntime().execute(
        lane=lane,
        prompt=prompt,
        run_dir=run_dir,
        deadline_seconds=60,
    )


async def test_valid_run_materializes_artifacts_and_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "slop-hygiene" / "r2"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())

    result = await execute_fixture(lane, run_dir)

    assert result.lane_id == lane.id
    assert result.replica == 2
    assert result.status is RunStatus.VALID
    assert result.output is not None
    assert result.output.verdict == "PASS"
    assert result.invalid_reason is None
    assert result.wall_seconds >= 0
    assert result.artifact_dir == run_dir
    assert (run_dir / "prompt.md").read_text(encoding="utf-8") == "Review this tiny diff."
    assert json.loads((run_dir / "schema.json").read_text(encoding="utf-8")) == lane.output_schema()
    assert calls == [
        (
            [
                "timeout",
                "--foreground",
                "--signal=TERM",
                "--kill-after=30s",
                "60s",
                "codex",
                "exec",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-c",
                "features.multi_agent=false",
                "-c",
                "features.collaboration_modes=false",
                "--output-schema",
                str(run_dir / "schema.json"),
                "-o",
                str(run_dir / "out.json"),
                "-",
            ],
            None,
        )
    ]


async def test_exit_124_is_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    install_spawn(monkeypatch, run_dir=run_dir, exit_code=124, payload=valid_payload())

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.output is None
    assert result.invalid_reason == "exit_nonzero:124"


async def test_missing_output_artifact_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    install_spawn(monkeypatch, run_dir=run_dir)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "missing_artifact"


async def test_malformed_json_is_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"

    async def fake_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cwd
        del cmd, stdin_text
        log_path.write_text("tokens used: 1\n", encoding="utf-8")
        (run_dir / "out.json").write_text("{not json", encoding="utf-8")
        return 0

    monkeypatch.setattr(codex_module, "_spawn", fake_spawn)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "json_parse_error"


async def test_out_of_enum_rule_id_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    payload = {
        "verdict": "ISSUES",
        "findings": [
            {
                "rule_id": "invented/not-in-lane",
                "file": "tiny.py",
                "line": 1,
                "severity": "warning",
                "body": "A scripted finding.",
            }
        ],
    }
    install_spawn(monkeypatch, run_dir=run_dir, payload=payload)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "schema_validation_error"


async def test_missing_completion_marker_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    install_spawn(
        monkeypatch,
        run_dir=run_dir,
        payload=valid_payload(),
        log_text="codex exited without its terminal marker\n",
    )

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "no_completion_marker"


async def test_execute_raw_uses_custom_schema_validator_and_workdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class RawOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        answer: str

    run_dir = tmp_path / "raw" / "r3"
    workdir = tmp_path / "checkout"
    workdir.mkdir()
    schema = RawOutput.model_json_schema()
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload={"answer": "yes"})

    result = await CodexRuntime().execute_raw(
        schema=schema,
        prompt="Decide this candidate.",
        run_dir=run_dir,
        deadline_seconds=45,
        workdir=workdir,
        validate=RawOutput.model_validate,
    )

    assert result.status is RunStatus.VALID
    assert isinstance(result.output, RawOutput)
    assert result.output.answer == "yes"
    assert json.loads((run_dir / "schema.json").read_text(encoding="utf-8")) == schema
    assert calls[0][1] == workdir


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux setpriv requirement")
async def test_spawn_fails_closed_when_setpriv_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_module, "_SETPRIV", None)

    with pytest.raises(RuntimeError, match=r"setpriv.*required"):
        await codex_module._spawn(["true"], "", tmp_path / "spawn.log")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_spawn_cancellation_terminates_and_reaps_runtime_child(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "cancel-child.pid"
    task = asyncio.create_task(
        codex_module._spawn(
            [
                "timeout",
                "--foreground",
                "--signal=TERM",
                "60s",
                sys.executable,
                "-c",
                _SLEEP_CHILD_SCRIPT,
                str(child_pid_path),
            ],
            "",
            tmp_path / "cancel-child.log",
        )
    )
    child_pids: tuple[int, int] | None = None
    try:
        async with asyncio.timeout(3):
            while not child_pid_path.exists():
                await asyncio.sleep(0.01)
        wrapper_pid, runtime_pid = child_pid_path.read_text(encoding="utf-8").split()
        child_pids = (int(wrapper_pid), int(runtime_pid))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with asyncio.timeout(3):
            while any(_linux_process_is_running(pid) for pid in child_pids):
                await asyncio.sleep(0.01)
        assert not any(_linux_process_is_running(pid) for pid in child_pids)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for child_pid in child_pids or ():
            if _linux_process_is_running(child_pid):
                os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux parent-death signal")
def test_spawned_runtime_child_terminates_after_parent_sigkill(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    log_path = tmp_path / "child.log"
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_PARENT_SCRIPT, str(child_pid_path), str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pids: tuple[int, int] | None = None
    try:
        ready_deadline = time.monotonic() + 3
        while time.monotonic() < ready_deadline:
            if child_pid_path.exists():
                wrapper_pid, runtime_pid = child_pid_path.read_text(encoding="utf-8").split()
                child_pids = (int(wrapper_pid), int(runtime_pid))
                break
            if parent.poll() is not None:
                stdout, stderr = parent.communicate()
                pytest.fail(f"spawn parent exited before readiness: {stdout=} {stderr=}")
            time.sleep(0.01)
        assert child_pids is not None, "runtime child did not signal readiness"

        parent.send_signal(signal.SIGKILL)
        parent.wait(timeout=3)

        exit_deadline = time.monotonic() + 3
        while (
            any(_linux_process_is_running(pid) for pid in child_pids)
            and time.monotonic() < exit_deadline
        ):
            time.sleep(0.01)
        assert not any(_linux_process_is_running(pid) for pid in child_pids)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        for child_pid in child_pids or ():
            if _linux_process_is_running(child_pid):
                os.kill(child_pid, signal.SIGKILL)


@pytest.mark.live
async def test_real_codex_returns_valid_result(tmp_path: Path) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    lane = load_lane(FIXTURE)
    fixture = tmp_path / "tiny.py"
    fixture.write_text("answer = 42\n", encoding="utf-8")
    prompt = (
        "Review this known-clean one-line fixture and return verdict PASS with no findings. "
        "Do not inspect any other files.\n\n"
        f"File: {fixture.name}\n```python\n{fixture.read_text(encoding='utf-8')}```"
    )

    result = await CodexRuntime().execute(
        lane=lane,
        prompt=prompt,
        run_dir=tmp_path / "live" / "r1",
        deadline_seconds=90,
    )

    assert result.status is RunStatus.VALID, result.invalid_reason
    assert result.output is not None
