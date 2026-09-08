from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict

import rvw.runtimes.codex as codex_module
from rvw.lane import Lane, load_lane
from rvw.runtime_policy import CodexRuntimePolicy
from rvw.runtimes import RunStatus, RunUsage, RunUsageStatus
from rvw.runtimes.codex import (
    CodexRuntime,
    CodexRuntimeMode,
    RuntimeLogCounts,
    count_runtime_log_turns,
    resolve_no_output_seconds,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lanes" / "slop-hygiene.md"
AGENTIC_THREE_EXECS_LOG = (
    Path(__file__).parent / "fixtures" / "runtime-logs" / "agentic-three-execs.log"
)
_TOOL_LESS_LOG = (
    "OpenAI Codex v0.152.0 (research preview)\n"
    "--------\n"
    "workdir: /work/checkout\n"
    "model: gpt-5.6-sol\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: max\n"
    "reasoning summaries: detailed\n"
    "session id: 0199a6f2-3c1e-7d4b-9b0e-6f1c2a8d5e74\n"
    "--------\n"
    "user\n"
    "Review only the supplied evidence.\n"
    "\n"
    "codex\n"
    "The supplied diff is clean.\n"
    "\n"
    "tokens used\n"
    "1,204\n"
)

_SLEEP_CHILD_SCRIPT = """
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(f"{os.getppid()} {os.getpid()}", encoding="utf-8")
time.sleep(60)
"""
_IGNORE_TERM_CHILD_SCRIPT = """
import os
import signal
import sys
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(f"{os.getppid()} {os.getpid()}", encoding="utf-8")
time.sleep(60)
"""
_LEADER_EXITS_CHILD_IGNORES_TERM_SCRIPT = f"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen(
    [sys.executable, "-c", {_IGNORE_TERM_CHILD_SCRIPT!r}, sys.argv[2]],
)
Path(sys.argv[1]).write_text(f"{{os.getpid()}} {{child.pid}}", encoding="utf-8")
while True:
    time.sleep(60)
"""
_SPAWN_PARENT_SCRIPT = f"""
import asyncio
import sys
from pathlib import Path

from rvw.runtimes.codex import _spawn


async def main() -> None:
    command = [
        sys.executable,
        "-c",
        {_SLEEP_CHILD_SCRIPT!r},
        sys.argv[1],
    ]
    await _spawn(command, "", Path(sys.argv[2]))


asyncio.run(main())
"""

_SILENT_RUNTIME_SCRIPT = """
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
print("OpenAI Codex fixture banner", flush=True)
time.sleep(60)
"""
_CHATTY_RUNTIME_SCRIPT = """
import json
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
for _ in range(7):
    sys.stdout.write(".")
    sys.stdout.flush()
    time.sleep(0.3)
Path(sys.argv[2]).write_text(
    json.dumps({"verdict": "PASS", "covered": [], "findings": []}), encoding="utf-8"
)
print("\\ntokens used: 7", flush=True)
"""
_LATE_SILENCE_RUNTIME_SCRIPT = """
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
for _ in range(10):
    sys.stdout.write(".")
    sys.stdout.flush()
    time.sleep(0.2)
time.sleep(60)
"""


def _linux_process_is_running(pid: int) -> bool:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat_text.rsplit(") ", maxsplit=1)[1][0] != "Z"


def _linux_process_exists(pid: int) -> bool:
    """True while the pid has a /proc entry, including an exited-but-unreaped zombie."""

    return Path(f"/proc/{pid}").exists()


def install_child_runtime(monkeypatch: pytest.MonkeyPatch, script: str, *script_args: str) -> None:
    """Route the real ``_spawn`` at a Python child so the watchdog sees a live process."""

    original_spawn = codex_module._spawn

    async def child_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cmd
        return await original_spawn(
            [sys.executable, "-c", script, *script_args], stdin_text, log_path, cwd=cwd
        )

    monkeypatch.setattr(codex_module, "_spawn", child_spawn)
    monkeypatch.setattr(codex_module, "_WATCHDOG_POLL_SECONDS", 0.05)


def _read_child_pid(pid_path: Path) -> int:
    return int(pid_path.read_text(encoding="utf-8").strip())


async def _wait_for_child_pid(pid_path: Path) -> int:
    async with asyncio.timeout(5):
        while not pid_path.exists() or not pid_path.read_text(encoding="utf-8").strip():
            await asyncio.sleep(0.01)
    return _read_child_pid(pid_path)


def _kill_if_running(pid_path: Path) -> None:
    if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip():
        pid = _read_child_pid(pid_path)
        if _linux_process_is_running(pid):
            os.kill(pid, signal.SIGKILL)


def valid_payload() -> dict[str, object]:
    return {"verdict": "PASS", "covered": [], "findings": []}


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


async def execute_fixture(
    lane: Lane,
    run_dir: Path,
    prompt: str = "Review this tiny diff.",
    workdir: Path | None = None,
):
    return await CodexRuntime().execute(
        lane=lane,
        prompt=prompt,
        run_dir=run_dir,
        deadline_seconds=60,
        workdir=workdir,
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
                "codex",
                "exec",
                "--model",
                "gpt-5.6-sol",
                "-c",
                'model_reasoning_effort="max"',
                "-c",
                'model_reasoning_summary="detailed"',
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
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.model == "gpt-5.6-sol"
    assert usage.reasoning_effort == "max"
    assert usage.status is RunUsageStatus.COMPLETED
    assert usage.cli_tokens_used == 42
    assert result.usage == usage


async def test_cancelled_runtime_persists_usage_before_propagating_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "cancel" / "r1"

    async def cancelled_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cmd, stdin_text, log_path, cwd
        raise asyncio.CancelledError

    monkeypatch.setattr(codex_module, "_spawn", cancelled_spawn)

    with pytest.raises(asyncio.CancelledError):
        await execute_fixture(lane, run_dir)

    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.CANCELED
    assert usage.cli_tokens_used is None
    assert usage.tool_calls is None
    assert usage.assistant_messages is None


async def test_runtime_policy_overrides_model_and_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "custom" / "r1"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())

    result = await CodexRuntime(
        policy=CodexRuntimePolicy(model="gpt-test", reasoning_effort="high")
    ).execute(
        lane=lane,
        prompt="Review this tiny diff.",
        run_dir=run_dir,
        deadline_seconds=60,
    )

    assert result.status is RunStatus.VALID
    command = calls[0][0]
    assert command[command.index("--model") + 1] == "gpt-test"
    config_index = command.index("-c", command.index("--model"))
    assert command[config_index + 1] == 'model_reasoning_effort="high"'


async def test_tool_less_runtime_disables_interactive_tools_and_records_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "tool-less" / "r1"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())

    result = await CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS).execute(
        lane=lane,
        prompt="Review only the supplied evidence.",
        run_dir=run_dir,
        deadline_seconds=60,
    )

    assert result.status is RunStatus.VALID
    command = calls[0][0]
    disabled_features = {
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--disable"
    }
    assert {
        "shell_tool",
        "browser_use",
        "in_app_browser",
        "computer_use",
        "apps",
        "plugins",
        "image_generation",
        "multi_agent",
        "collaboration_modes",
    } <= disabled_features
    assert "--ignore-rules" in command
    assert "--ephemeral" in command
    assert 'web_search="disabled"' in command
    assert "allow_login_shell=false" in command
    assert result.usage is not None
    assert result.usage.runtime_mode == "tool-less"
    assert result.usage.tool_calls == 0


@pytest.mark.parametrize("mode", list(CodexRuntimeMode))
async def test_container_can_select_danger_full_access_sandbox_for_each_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: CodexRuntimeMode
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / mode / "r1"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())
    monkeypatch.setenv("RVW_CODEX_SANDBOX", "danger-full-access")

    result = await CodexRuntime(mode=mode).execute(
        lane=lane,
        prompt="Review this tiny diff.",
        run_dir=run_dir,
        deadline_seconds=60,
    )

    assert result.status is RunStatus.VALID
    command = calls[0][0]
    assert command[command.index("--sandbox") + 1] == "danger-full-access"


async def test_invalid_sandbox_environment_fails_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "slop-hygiene" / "r1"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())
    monkeypatch.setenv("RVW_CODEX_SANDBOX", "workspace-write")

    with pytest.raises(ValueError, match="RVW_CODEX_SANDBOX"):
        await execute_fixture(lane, run_dir)

    assert calls == []


async def test_exit_124_is_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    install_spawn(monkeypatch, run_dir=run_dir, exit_code=124, payload=valid_payload())

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.output is None
    assert result.invalid_reason == "exit_nonzero:124"
    assert result.diagnostic is not None
    assert result.diagnostic.exit_code == 124
    assert result.diagnostic.log_path == str(run_dir / "run.log")
    assert result.diagnostic.output_path == str(run_dir / "out.json")


async def test_spawn_failure_retains_inspectable_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"

    async def failed_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cmd, stdin_text, log_path, cwd
        raise FileNotFoundError("missing checkout")

    monkeypatch.setattr(codex_module, "_spawn", failed_spawn)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "spawn_error:FileNotFoundError"
    assert result.diagnostic is not None
    assert result.diagnostic.detail == "FileNotFoundError: missing checkout"
    assert result.diagnostic.log_path == str(run_dir / "run.log")
    assert result.diagnostic.output_path == str(run_dir / "out.json")


async def test_deadline_cancels_spawn_and_returns_timeout_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "deadline" / "r1"
    spawn_started = asyncio.Event()
    spawn_cancelled = asyncio.Event()

    async def blocking_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cmd, stdin_text, log_path, cwd
        spawn_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            spawn_cancelled.set()
            raise
        return 0

    monkeypatch.setattr(codex_module, "_spawn", blocking_spawn)

    result = await CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS).execute(
        lane=lane,
        prompt="Review this tiny diff.",
        run_dir=run_dir,
        deadline_seconds=1,
    )

    assert spawn_started.is_set()
    assert spawn_cancelled.is_set()
    assert result.status is RunStatus.INVALID
    assert result.output is None
    assert result.invalid_reason == "exit_nonzero:124"
    assert result.usage is not None
    assert result.usage.status is RunUsageStatus.INVALID


async def test_missing_output_artifact_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    install_spawn(monkeypatch, run_dir=run_dir)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "missing"
    assert result.diagnostic is not None
    assert result.diagnostic.output_bytes is None


async def test_empty_output_artifact_is_distinct_from_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"

    async def fake_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cwd, cmd, stdin_text
        log_path.write_text("", encoding="utf-8")
        (run_dir / "out.json").write_bytes(b"")
        return 0

    monkeypatch.setattr(codex_module, "_spawn", fake_spawn)

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "empty"
    assert result.output is None
    assert result.diagnostic is not None
    assert result.diagnostic.log_bytes == 0
    assert result.diagnostic.output_bytes == 0


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
    assert result.invalid_reason == "unparseable"
    assert result.diagnostic is not None
    assert result.diagnostic.output_bytes == len("{not json")


async def test_out_of_enum_rule_id_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "r1"
    payload = {
        "verdict": "ISSUES",
        "covered": [],
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
    assert result.invalid_reason == "schema-invalid"
    assert result.diagnostic is not None
    assert result.diagnostic.output_bytes is not None


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


async def test_lane_execute_forwards_discovery_workdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "slop-hygiene" / "r1"
    workdir = tmp_path / "checkout"
    workdir.mkdir()
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())

    result = await execute_fixture(lane, run_dir, workdir=workdir)

    assert result.status is RunStatus.VALID
    assert calls[0][1] == workdir
    command = calls[0][0]
    codex_index = command.index("codex")
    assert command[codex_index : codex_index + 2] == ["codex", "exec"]
    assert "review" not in command


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux setpriv requirement")
async def test_spawn_fails_closed_when_setpriv_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_module, "_SETPRIV", None)

    with pytest.raises(RuntimeError, match=r"setpriv.*required"):
        await codex_module._spawn(["true"], "", tmp_path / "spawn.log")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_spawn_cancellation_terminates_runtime_process_tree(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "cancel-child.pid"
    task = asyncio.create_task(
        codex_module._spawn(
            [
                sys.executable,
                "-c",
                _SLEEP_CHILD_SCRIPT,
                str(child_pid_path),
            ],
            "",
            tmp_path / "cancel-child.log",
        )
    )
    process_tree_pids: tuple[int, ...] | None = None
    try:
        async with asyncio.timeout(3):
            while not child_pid_path.exists():
                await asyncio.sleep(0.01)
        _, runtime_pid_text = child_pid_path.read_text(encoding="utf-8").split()
        runtime_pid = int(runtime_pid_text)
        assert runtime_pid != os.getpid()
        process_tree_pids = (runtime_pid,)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with asyncio.timeout(3):
            while any(_linux_process_is_running(pid) for pid in process_tree_pids):
                await asyncio.sleep(0.01)
        assert not any(_linux_process_is_running(pid) for pid in process_tree_pids)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for child_pid in process_tree_pids or ():
            if _linux_process_is_running(child_pid):
                os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_spawn_cancellation_sigkills_term_ignoring_process_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.2)
    child_pid_path = tmp_path / "ignore-term-child.pid"
    log_path = tmp_path / "ignore-term-child.log"
    task = asyncio.create_task(
        codex_module._spawn(
            [
                sys.executable,
                "-c",
                _IGNORE_TERM_CHILD_SCRIPT,
                str(child_pid_path),
            ],
            "",
            log_path,
        )
    )
    process_tree_pids: tuple[int, ...] | None = None
    try:
        async with asyncio.timeout(3):
            while not child_pid_path.exists():
                await asyncio.sleep(0.01)
        _, runtime_pid_text = child_pid_path.read_text(encoding="utf-8").split()
        runtime_pid = int(runtime_pid_text)
        assert runtime_pid != os.getpid()
        process_tree_pids = (runtime_pid,)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with asyncio.timeout(3):
            while any(_linux_process_is_running(pid) for pid in process_tree_pids):
                await asyncio.sleep(0.01)
        assert not any(_linux_process_is_running(pid) for pid in process_tree_pids)
        log_text = log_path.read_text(encoding="utf-8")
        assert "rvw: graceful termination timed out after 0.2s" in log_text
        assert "escalated to SIGKILL (pgid " in log_text
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for child_pid in process_tree_pids or ():
            if _linux_process_is_running(child_pid):
                os.kill(child_pid, signal.SIGKILL)


async def test_terminate_and_reap_returns_when_process_group_persists_after_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReapedProcess:
        pid = 123
        returncode: int | None = None

        async def wait(self) -> int:
            return 0

    async def never_exits(_: int) -> None:
        await asyncio.Future()

    signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(codex_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(codex_module, "_wait_for_process_group_exit", never_exits)
    monkeypatch.setattr(
        codex_module.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )
    log_file = BytesIO()

    await asyncio.wait_for(
        codex_module._terminate_and_reap(
            cast(asyncio.subprocess.Process, ReapedProcess()),
            log_file,
            pgid=123,
        ),
        timeout=0.1,
    )

    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert log_file.getvalue().decode("utf-8") == (
        "rvw: graceful termination timed out after 0.01s; escalated to SIGKILL (pgid 123)\n"
        "rvw: process group remained after SIGKILL for 0.01s; continuing cleanup (pgid 123)\n"
    )


async def test_terminate_and_reap_returns_when_post_kill_group_probe_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReapedProcess:
        pid = 123
        returncode: int | None = None

        async def wait(self) -> int:
            return 0

    signals: list[tuple[int, signal.Signals | int]] = []
    sent_kill = False

    def fake_killpg(pgid: int, sig: signal.Signals | int) -> None:
        nonlocal sent_kill
        signals.append((pgid, sig))
        if sig == signal.SIGKILL:
            sent_kill = True
        if sig == 0 and sent_kill:
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(codex_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(codex_module.os, "killpg", fake_killpg)
    log_file = BytesIO()

    await asyncio.wait_for(
        codex_module._terminate_and_reap(
            cast(asyncio.subprocess.Process, ReapedProcess()),
            log_file,
            pgid=123,
        ),
        timeout=0.1,
    )

    assert signals[0] == (123, signal.SIGTERM)
    assert (123, signal.SIGKILL) in signals
    assert log_file.getvalue().decode("utf-8") == (
        "rvw: graceful termination timed out after 0.01s; escalated to SIGKILL (pgid 123)\n"
        "rvw: process group could not be verified after SIGKILL; continuing cleanup "
        "(pgid 123)\n"
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_spawn_cancellation_kills_child_after_term_exits_its_leader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.2)
    pid_path = tmp_path / "leader-child.pid"
    child_pid_path = tmp_path / "ignored-child.pid"
    log_path = tmp_path / "leader-child.log"
    task = asyncio.create_task(
        codex_module._spawn(
            [
                sys.executable,
                "-c",
                _LEADER_EXITS_CHILD_IGNORES_TERM_SCRIPT,
                str(pid_path),
                str(child_pid_path),
            ],
            "",
            log_path,
        )
    )
    process_tree_pids: tuple[int, int] | None = None
    try:
        async with asyncio.timeout(3):
            while not pid_path.exists() or not child_pid_path.exists():
                await asyncio.sleep(0.01)
        leader_pid, child_pid = pid_path.read_text(encoding="utf-8").split()
        process_tree_pids = (int(leader_pid), int(child_pid))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with asyncio.timeout(3):
            while any(_linux_process_is_running(pid) for pid in process_tree_pids):
                await asyncio.sleep(0.01)
        assert not any(_linux_process_is_running(pid) for pid in process_tree_pids)
        assert "escalated to SIGKILL (pgid " in log_path.read_text(encoding="utf-8")
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for child_pid in process_tree_pids or ():
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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_watchdog_kills_silent_runtime_and_reaps_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "silent" / "r1"
    pid_path = tmp_path / "silent.pid"
    install_child_runtime(monkeypatch, _SILENT_RUNTIME_SCRIPT, str(pid_path))

    try:
        async with asyncio.timeout(20):
            result = await CodexRuntime(no_output_seconds=1).execute(
                lane=lane,
                prompt="Review this tiny diff.",
                run_dir=run_dir,
                deadline_seconds=30,
            )
        assert not _linux_process_exists(_read_child_pid(pid_path))
    finally:
        _kill_if_running(pid_path)

    assert result.status is RunStatus.INVALID
    assert result.output is None
    assert result.invalid_reason == "no_output_after:1s"
    assert result.diagnostic is not None
    assert result.diagnostic.exit_code is None
    assert result.diagnostic.detail is not None
    assert "did not grow" in result.diagnostic.detail
    assert 1 <= result.wall_seconds < 10
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.INVALID
    assert usage.cli_tokens_used is None
    assert usage.no_output_seconds == 1
    assert result.usage == usage
    assert "fixture banner" in (run_dir / "run.log").read_text(encoding="utf-8")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_watchdog_tolerates_a_runtime_that_keeps_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "chatty" / "r1"
    pid_path = tmp_path / "chatty.pid"
    install_child_runtime(
        monkeypatch, _CHATTY_RUNTIME_SCRIPT, str(pid_path), str(run_dir / "out.json")
    )

    try:
        async with asyncio.timeout(20):
            result = await CodexRuntime(no_output_seconds=1).execute(
                lane=lane,
                prompt="Review this tiny diff.",
                run_dir=run_dir,
                deadline_seconds=30,
            )
        assert not _linux_process_exists(_read_child_pid(pid_path))
    finally:
        _kill_if_running(pid_path)

    assert result.status is RunStatus.VALID, result.invalid_reason
    assert result.output is not None
    assert result.output.verdict == "PASS"
    assert result.usage is not None
    assert result.usage.status is RunUsageStatus.COMPLETED
    assert result.usage.cli_tokens_used == 7
    assert result.wall_seconds >= 2


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_deadline_wins_when_no_output_timeout_is_longer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "deadline-first" / "r1"
    pid_path = tmp_path / "deadline-first.pid"
    install_child_runtime(monkeypatch, _SILENT_RUNTIME_SCRIPT, str(pid_path))

    try:
        async with asyncio.timeout(20):
            result = await CodexRuntime(no_output_seconds=5).execute(
                lane=lane,
                prompt="Review this tiny diff.",
                run_dir=run_dir,
                deadline_seconds=1,
            )
        assert not _linux_process_exists(_read_child_pid(pid_path))
    finally:
        _kill_if_running(pid_path)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "exit_nonzero:124"
    assert result.usage is not None
    assert result.usage.status is RunUsageStatus.INVALID
    assert result.wall_seconds < 10


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_deadline_wins_when_silence_begins_inside_the_last_watchdog_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The runtime writes for ~2 s and falls silent with fewer than N=2 s left before 3 s."""

    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "late-silence" / "r1"
    pid_path = tmp_path / "late-silence.pid"
    install_child_runtime(monkeypatch, _LATE_SILENCE_RUNTIME_SCRIPT, str(pid_path))

    try:
        async with asyncio.timeout(20):
            result = await CodexRuntime(no_output_seconds=2).execute(
                lane=lane,
                prompt="Review this tiny diff.",
                run_dir=run_dir,
                deadline_seconds=3,
            )
        assert not _linux_process_exists(_read_child_pid(pid_path))
    finally:
        _kill_if_running(pid_path)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "exit_nonzero:124"
    assert 3 <= result.wall_seconds < 10
    assert (run_dir / "run.log").read_text(encoding="utf-8").startswith(".")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process inspection")
async def test_cancellation_during_watchdog_leaves_no_zombie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "cancelled" / "r1"
    pid_path = tmp_path / "cancelled.pid"
    install_child_runtime(monkeypatch, _SILENT_RUNTIME_SCRIPT, str(pid_path))
    task = asyncio.create_task(
        CodexRuntime(no_output_seconds=30).execute(
            lane=lane,
            prompt="Review this tiny diff.",
            run_dir=run_dir,
            deadline_seconds=60,
        )
    )

    try:
        child_pid = await _wait_for_child_pid(pid_path)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=20)
        assert done == {task}
        assert task.cancelled()
        async with asyncio.timeout(5):
            while _linux_process_exists(child_pid):
                await asyncio.sleep(0.01)
        assert not _linux_process_exists(child_pid)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        _kill_if_running(pid_path)

    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.CANCELED


def install_fake_spawn_with_cancel_handler(
    monkeypatch: pytest.MonkeyPatch,
    on_cancel,
) -> None:
    """Install a process-free ``_spawn`` that writes a banner, blocks, and runs ``on_cancel``."""

    async def fake_spawn(
        cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
    ) -> int:
        del cmd, stdin_text, cwd
        log_path.write_bytes(b"fixture banner\n")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await on_cancel()
            raise
        raise AssertionError("unreachable")

    monkeypatch.setattr(codex_module, "_spawn", fake_spawn)
    monkeypatch.setattr(codex_module, "_WATCHDOG_POLL_SECONDS", 0.01)


def _raw_execute(runtime: CodexRuntime, run_dir: Path, *, deadline_seconds: int):
    return runtime.execute_raw(
        schema={},
        prompt="Review this tiny diff.",
        run_dir=run_dir,
        deadline_seconds=deadline_seconds,
        validate=lambda raw: cast(BaseModel, raw),
    )


async def test_cancellation_while_the_watchdog_reaps_propagates_after_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "reap-cancel" / "r1"
    reaping = asyncio.Event()
    release = asyncio.Event()

    async def slow_reap() -> None:
        reaping.set()
        await release.wait()

    install_fake_spawn_with_cancel_handler(monkeypatch, slow_reap)
    task = asyncio.create_task(
        _raw_execute(CodexRuntime(no_output_seconds=1), run_dir, deadline_seconds=30)
    )

    async with asyncio.timeout(10):
        await reaping.wait()
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done(), "cancellation must wait for the reap to finish"
        release.set()
        done, _ = await asyncio.wait({task})
    assert done == {task}
    assert task.cancelled()
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.CANCELED


async def test_cancellation_landing_as_the_reaped_spawn_settles_still_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dispatcher cancel one loop tick after the spawn task settles must not be swallowed."""

    run_dir = tmp_path / "same-tick-cancel" / "r1"
    loop = asyncio.get_running_loop()
    holder: dict[str, asyncio.Task[object]] = {}

    async def cancel_outer_next_tick() -> None:
        loop.call_soon(loop.call_soon, holder["outer"].cancel)

    install_fake_spawn_with_cancel_handler(monkeypatch, cancel_outer_next_tick)
    task = asyncio.create_task(
        _raw_execute(CodexRuntime(no_output_seconds=1), run_dir, deadline_seconds=30)
    )
    holder["outer"] = cast(asyncio.Task[object], task)

    async with asyncio.timeout(10):
        done, _ = await asyncio.wait({task})
    assert done == {task}
    assert task.cancelled(), "the external cancel was misread as the watchdog's own kill"
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.CANCELED


async def test_watchdog_kill_keeps_its_reason_when_the_deadline_expires_during_the_reap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Watchdog at 1 s, deadline at 2 s, reap lasts 2 s: whichever fired first wins."""

    run_dir = tmp_path / "deadline-during-reap" / "r1"

    async def slow_reap() -> None:
        await asyncio.sleep(2)

    install_fake_spawn_with_cancel_handler(monkeypatch, slow_reap)

    async with asyncio.timeout(10):
        result = await _raw_execute(CodexRuntime(no_output_seconds=1), run_dir, deadline_seconds=2)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "no_output_after:1s"
    assert result.diagnostic is not None
    assert result.diagnostic.detail is not None
    assert "did not grow" in result.diagnostic.detail
    assert result.wall_seconds >= 3
    assert result.usage is not None
    assert result.usage.status is RunUsageStatus.INVALID


async def test_watchdog_surfaces_a_failed_reap_instead_of_a_clean_kill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "reap-failed" / "r1"

    async def failing_reap() -> None:
        raise PermissionError("killpg failed; process group may still be running")

    install_fake_spawn_with_cancel_handler(monkeypatch, failing_reap)

    async with asyncio.timeout(10):
        result = await _raw_execute(CodexRuntime(no_output_seconds=1), run_dir, deadline_seconds=30)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "spawn_error:PermissionError"
    assert result.diagnostic is not None
    assert result.diagnostic.detail == (
        "PermissionError: killpg failed; process group may still be running"
    )
    assert result.usage is not None
    assert result.usage.status is RunUsageStatus.INVALID


async def test_runtime_argv_requests_reasoning_summaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "summaries" / "r1"
    calls = install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload())

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.VALID
    command = calls[0][0]
    effort_index = command.index('model_reasoning_effort="max"')
    assert command[effort_index + 1 : effort_index + 3] == [
        "-c",
        'model_reasoning_summary="detailed"',
    ]
    assert command.index("--model") < effort_index
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.reasoning_summary == "detailed"
    assert usage.no_output_seconds == 660
    assert result.usage is not None
    assert result.usage.reasoning_summary == "detailed"


def test_runtime_policy_rejects_unknown_reasoning_summary() -> None:
    with pytest.raises(ValueError, match="reasoning_summary"):
        CodexRuntimePolicy(model="gpt-test", reasoning_effort="high", reasoning_summary="loud")


def test_runtime_policy_renders_a_custom_reasoning_summary() -> None:
    policy = CodexRuntimePolicy(model="gpt-test", reasoning_effort="high", reasoning_summary="none")

    assert policy.command_args()[-2:] == ("-c", 'model_reasoning_summary="none"')
    assert policy.payload()["reasoning_summary"] == "none"


def test_legacy_usage_without_reasoning_summary_loads() -> None:
    usage = RunUsage.model_validate(
        {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "status": "completed",
            "wall_seconds": 1.5,
        }
    )

    assert usage.reasoning_summary is None
    assert usage.no_output_seconds is None
    assert usage.tool_calls is None
    assert usage.assistant_messages is None


def test_resolve_no_output_seconds_prefers_explicit_then_environment_then_default() -> None:
    assert resolve_no_output_seconds(120, {"RVW_NO_OUTPUT_SECONDS": "90"}) == 120
    assert resolve_no_output_seconds(None, {"RVW_NO_OUTPUT_SECONDS": "90"}) == 90
    assert resolve_no_output_seconds(None, {}) == 660
    assert codex_module.DEFAULT_NO_OUTPUT_SECONDS == 660
    assert codex_module.NO_OUTPUT_SECONDS_ENV == "RVW_NO_OUTPUT_SECONDS"


def test_resolve_no_output_seconds_reads_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVW_NO_OUTPUT_SECONDS", "75")

    assert resolve_no_output_seconds(None) == 75

    monkeypatch.delenv("RVW_NO_OUTPUT_SECONDS")

    assert resolve_no_output_seconds(None) == 660


@pytest.mark.parametrize("value", ["0", "abc", "-5", "1.5", ""])
def test_resolve_no_output_seconds_rejects_non_positive_environment(value: str) -> None:
    with pytest.raises(ValueError, match="RVW_NO_OUTPUT_SECONDS"):
        resolve_no_output_seconds(None, {"RVW_NO_OUTPUT_SECONDS": value})


def test_resolve_no_output_seconds_rejects_non_positive_explicit_value() -> None:
    with pytest.raises(ValueError, match="no_output_seconds"):
        resolve_no_output_seconds(0, {})


@pytest.mark.parametrize("value", [0, -1])
def test_runtime_rejects_non_positive_no_output_seconds(value: int) -> None:
    with pytest.raises(ValueError, match="no_output_seconds"):
        CodexRuntime(no_output_seconds=value)


def test_runtime_defaults_no_output_seconds_to_the_measured_ceiling() -> None:
    assert CodexRuntime().no_output_seconds == 660
    assert CodexRuntime(no_output_seconds=120).no_output_seconds == 120


def test_count_runtime_log_turns_counts_exec_and_codex_headers_in_the_fixture() -> None:
    text = AGENTIC_THREE_EXECS_LOG.read_text(encoding="utf-8")

    assert "\n  exec\n" in text, "the fixture must carry an indented exec line that must not count"
    assert count_runtime_log_turns(text) == RuntimeLogCounts(tool_calls=3, assistant_messages=3)


def test_count_runtime_log_turns_on_a_tool_less_log() -> None:
    assert count_runtime_log_turns(_TOOL_LESS_LOG) == RuntimeLogCounts(
        tool_calls=0, assistant_messages=1
    )


def test_count_runtime_log_turns_on_empty_text() -> None:
    assert count_runtime_log_turns("") == RuntimeLogCounts(tool_calls=0, assistant_messages=0)


def test_count_runtime_log_turns_strips_a_trailing_carriage_return() -> None:
    text = "exec\r\n/bin/bash -lc 'git status' in /work/checkout\r\ncodex\r\nDone.\r\n"

    assert count_runtime_log_turns(text) == RuntimeLogCounts(tool_calls=1, assistant_messages=1)


def test_count_runtime_log_turns_ignores_prefixed_or_suffixed_headers() -> None:
    text = " exec\nexec \nexec:\ncodex said\n\tcodex\nexecute\n"

    assert count_runtime_log_turns(text) == RuntimeLogCounts(tool_calls=0, assistant_messages=0)


async def test_agentic_usage_records_tool_calls_and_assistant_messages_from_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "agentic" / "r1"
    install_spawn(
        monkeypatch,
        run_dir=run_dir,
        payload=valid_payload(),
        log_text=AGENTIC_THREE_EXECS_LOG.read_text(encoding="utf-8"),
    )

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.VALID
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.runtime_mode == "agentic"
    assert usage.status is RunUsageStatus.COMPLETED
    assert usage.tool_calls == 3
    assert usage.assistant_messages == 3
    assert usage.cli_tokens_used == 14203
    assert result.usage == usage


async def test_tool_less_usage_records_zero_tool_calls_and_counted_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "tool-less" / "r1"
    install_spawn(monkeypatch, run_dir=run_dir, payload=valid_payload(), log_text=_TOOL_LESS_LOG)

    result = await CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS).execute(
        lane=lane,
        prompt="Review only the supplied evidence.",
        run_dir=run_dir,
        deadline_seconds=60,
    )

    assert result.status is RunStatus.VALID
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.runtime_mode == "tool-less"
    assert usage.tool_calls == 0
    assert usage.assistant_messages == 1
    assert usage.cli_tokens_used == 1204


async def test_tool_less_usage_never_counts_tool_calls_from_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "tool-less-execs" / "r1"
    install_spawn(
        monkeypatch,
        run_dir=run_dir,
        payload=valid_payload(),
        log_text=AGENTIC_THREE_EXECS_LOG.read_text(encoding="utf-8"),
    )

    result = await CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS).execute(
        lane=lane,
        prompt="Review only the supplied evidence.",
        run_dir=run_dir,
        deadline_seconds=60,
    )

    assert result.usage is not None
    assert result.usage.tool_calls == 0
    assert result.usage.assistant_messages == 3


async def test_invalid_run_still_records_tool_call_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lane = load_lane(FIXTURE)
    run_dir = tmp_path / "killed" / "r1"
    install_spawn(
        monkeypatch,
        run_dir=run_dir,
        exit_code=124,
        log_text=AGENTIC_THREE_EXECS_LOG.read_text(encoding="utf-8"),
    )

    result = await execute_fixture(lane, run_dir)

    assert result.status is RunStatus.INVALID
    assert result.invalid_reason == "exit_nonzero:124"
    usage = RunUsage.model_validate_json((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage.status is RunUsageStatus.INVALID
    assert usage.tool_calls == 3
    assert usage.assistant_messages == 3


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

    result = await CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS).execute(
        lane=lane,
        prompt=prompt,
        run_dir=tmp_path / "live" / "r1",
        deadline_seconds=90,
    )

    assert result.status is RunStatus.VALID, result.invalid_reason
    assert result.output is not None
