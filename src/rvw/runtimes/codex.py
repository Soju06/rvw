"""Read-only ``codex exec`` runtime adapter."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, cast

from pydantic import BaseModel, ValidationError

from rvw.lane import Lane
from rvw.runtime_policy import DEFAULT_CODEX_RUNTIME_POLICY, CodexRuntimePolicy
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, RunUsage, RunUsageStatus
from rvw.schema import RuntimeLaneOutput

_REPLICA_DIRECTORY = re.compile(r"r([1-9][0-9]*)")
_COMPLETION_MARKER = "tokens used"
_CLI_TOKENS_USED = re.compile(r"tokens used\s*(?::\s*|\n\s*)([\d,]+)", re.IGNORECASE)
_PROCESS_TERMINATION_TIMEOUT_SECONDS = 5
_SETPRIV = shutil.which("setpriv") if sys.platform.startswith("linux") else None
_TOOL_LESS_DISABLED_FEATURES = (
    "shell_tool",
    "browser_use",
    "in_app_browser",
    "computer_use",
    "apps",
    "plugins",
    "image_generation",
    "multi_agent",
    "collaboration_modes",
)
_SANDBOX_ENV = "RVW_CODEX_SANDBOX"
_SANDBOX_VALUES = frozenset({"read-only", "danger-full-access"})
DEFAULT_NO_OUTPUT_SECONDS = 660
NO_OUTPUT_SECONDS_ENV = "RVW_NO_OUTPUT_SECONDS"
NO_OUTPUT_REASON_PREFIX = "no_output_after:"
_WATCHDOG_POLL_SECONDS = 2.0
# The runtime child, and every tool command it spawns, runs in the review phase: the image's
# PATH shims refuse remote git, gh, curl, and wget when RVW_PHASE is "review", and git's own
# transport check refuses every remote protocol regardless of which git binary is invoked.
# The rvw process itself never carries these values, so its checkout and publication keep
# their network access.
REVIEW_PHASE_ENVIRONMENT: Mapping[str, str] = {"RVW_PHASE": "review", "GIT_ALLOW_PROTOCOL": "none"}


def _sandbox_mode() -> str:
    value = os.environ.get(_SANDBOX_ENV, "read-only")
    if value not in _SANDBOX_VALUES:
        allowed = ", ".join(sorted(_SANDBOX_VALUES))
        raise ValueError(f"{_SANDBOX_ENV} must be one of: {allowed}")
    return value


def resolve_no_output_seconds(explicit: int | None, environ: Mapping[str, str] = os.environ) -> int:
    """Resolve the no-output watchdog: explicit option, then environment, then default."""

    if explicit is not None:
        if explicit < 1:
            raise ValueError("no_output_seconds must be at least 1")
        return explicit
    raw = environ.get(NO_OUTPUT_SECONDS_ENV)
    if raw is None:
        return DEFAULT_NO_OUTPUT_SECONDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{NO_OUTPUT_SECONDS_ENV} must be a positive integer, got {raw!r}"
        ) from exc
    if value < 1:
        raise ValueError(f"{NO_OUTPUT_SECONDS_ENV} must be a positive integer, got {raw!r}")
    return value


class CodexRuntimeMode(StrEnum):
    """The evidence and tool boundary for one Codex execution."""

    TOOL_LESS = "tool-less"
    AGENTIC = "agentic"


@dataclass(frozen=True, slots=True)
class RuntimeLogCounts:
    """Tool commands and assistant messages counted from a Codex ``run.log``."""

    tool_calls: int
    assistant_messages: int


def count_runtime_log_turns(log_text: str) -> RuntimeLogCounts:
    """Count the ``exec`` and ``codex`` item headers the Codex human output prints.

    Codex prints a line that is exactly ``exec`` before each tool command and a line
    that is exactly ``codex`` before each assistant message. Only whole lines match,
    after stripping a trailing carriage return, so an indented or prefixed ``exec``
    inside tool output does not count. The counts are telemetry: a tool whose output
    contains such a bare line can over-count, which is why nothing is enforced on them.
    """

    tool_calls = 0
    assistant_messages = 0
    for raw_line in log_text.split("\n"):
        line = raw_line.removesuffix("\r")
        if line == "exec":
            tool_calls += 1
        elif line == "codex":
            assistant_messages += 1
    return RuntimeLogCounts(tool_calls=tool_calls, assistant_messages=assistant_messages)


def _process_group_exists(pgid: int) -> bool:
    with suppress(ProcessLookupError):
        os.killpg(pgid, 0)
        return True
    return False


async def _wait_for_process_group_exit(pgid: int) -> None:
    while _process_group_exists(pgid):
        await asyncio.sleep(0.01)


async def _terminate_and_reap(
    process: asyncio.subprocess.Process,
    log_file: BinaryIO,
    *,
    pgid: int | None,
) -> None:
    """Terminate a started subprocess, escalating to SIGKILL after a bounded wait."""

    if pgid is None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS,
                )
                return
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
                signal_target = f"pid {process.pid}"
                marker = (
                    "rvw: graceful termination timed out after "
                    f"{_PROCESS_TERMINATION_TIMEOUT_SECONDS}s; escalated to SIGKILL "
                    f"({signal_target})\n"
                )
                log_file.write(marker.encode("utf-8"))
                log_file.flush()
        return

    with suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGTERM)
    leader_wait = asyncio.create_task(process.wait()) if process.returncode is None else None
    process_group_persisted = False
    process_group_unverified = False
    try:
        await asyncio.wait_for(
            _wait_for_process_group_exit(pgid),
            timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
        try:
            await asyncio.wait_for(
                _wait_for_process_group_exit(pgid),
                timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            process_group_persisted = True
        except PermissionError:
            process_group_unverified = True
        marker = (
            "rvw: graceful termination timed out after "
            f"{_PROCESS_TERMINATION_TIMEOUT_SECONDS}s; escalated to SIGKILL "
            f"(pgid {pgid})\n"
        )
        log_file.write(marker.encode("utf-8"))
        if process_group_persisted:
            marker = (
                "rvw: process group remained after SIGKILL for "
                f"{_PROCESS_TERMINATION_TIMEOUT_SECONDS}s; continuing cleanup "
                f"(pgid {pgid})\n"
            )
            log_file.write(marker.encode("utf-8"))
        if process_group_unverified:
            marker = (
                "rvw: process group could not be verified after SIGKILL; "
                f"continuing cleanup (pgid {pgid})\n"
            )
            log_file.write(marker.encode("utf-8"))
        log_file.flush()
    if leader_wait is not None:
        if process_group_persisted or process_group_unverified:
            leader_wait.cancel()
            with suppress(asyncio.CancelledError):
                await leader_wait
            return
        await leader_wait


async def _cleanup_before_unwind(
    process: asyncio.subprocess.Process,
    log_file: BinaryIO,
    *,
    pgid: int | None,
) -> None:
    """Finish subprocess cleanup even if the awaiting task is cancelled again."""

    cleanup = asyncio.create_task(_terminate_and_reap(process, log_file, pgid=pgid))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


def review_phase_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the runtime child's environment: the parent's plus the review-phase markers."""

    return {**(os.environ if base is None else base), **REVIEW_PHASE_ENVIRONMENT}


async def _spawn(
    cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
) -> int:
    """Run a command without a shell, in the review phase, combining its output in one log."""

    spawn_command = cmd
    if sys.platform.startswith("linux"):
        if _SETPRIV is None:
            raise RuntimeError("setpriv is required for Linux runtime parent-death coupling")
        spawn_command = [_SETPRIV, "--pdeathsig", "SIGTERM", *cmd]
    with log_path.open("wb") as log_file:
        process = await asyncio.create_subprocess_exec(
            *spawn_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=review_phase_environment(),
            start_new_session=True,
        )
        pgid = process.pid if os.name == "posix" else None
        try:
            await process.communicate(stdin_text.encode("utf-8"))
        except BaseException:
            await _cleanup_before_unwind(process, log_file, pgid=pgid)
            raise
    if process.returncode is None:
        raise RuntimeError("subprocess completed without a return code")
    return process.returncode


def _log_size(log_path: Path) -> int:
    """Return the combined log size, or 0 before the runtime has created the file."""

    try:
        return log_path.stat().st_size
    except OSError:
        return 0


@dataclass(slots=True)
class _WatchdogState:
    """Whether the watchdog terminated the runtime, so a later deadline cannot reclassify it."""

    fired: bool = False


async def _await_cancelled_spawn(spawn_task: asyncio.Task[int]) -> bool:
    """Wait for a cancelled spawn task to finish terminating and reaping its process group.

    Cancellation of the waiting task is absorbed so cleanup always completes; the return
    value reports whether such a cancellation arrived while waiting. The waiting task's
    own cancel count is the discriminator: the ``CancelledError`` that ``shield`` raises
    when the spawn task settles never increments it, while ``Task.cancel`` from the
    deadline or the dispatcher always does, even when both land in the same loop tick.
    """

    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("_await_cancelled_spawn requires a running task")
    cancels_before = task.cancelling()
    while not spawn_task.done():
        try:
            await asyncio.shield(spawn_task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.cancelling() > cancels_before


def _spawn_cleanup_error(spawn_task: asyncio.Task[int]) -> BaseException | None:
    """Return the exception a settled spawn task ended with, marking it retrieved."""

    if spawn_task.cancelled():
        return None
    return spawn_task.exception()


async def _spawn_with_watchdog(
    cmd: list[str],
    stdin_text: str,
    log_path: Path,
    *,
    cwd: Path | None,
    no_output_seconds: int,
    state: _WatchdogState,
) -> int | None:
    """Run ``_spawn`` as a task and cancel it once the combined log stops growing.

    Returns the runtime exit code, or ``None`` when the watchdog terminated the runtime
    because ``log_path`` did not grow for ``no_output_seconds``; ``state.fired`` is set
    before that kill starts so a deadline expiring while the kill is reaped does not
    reclassify it. Growth is measured on the combined stdout and stderr log, so a runtime
    that keeps reporting reconnects stays alive. The silence clock starts at spawn time,
    so a runtime that never writes a byte is terminated after the same interval. Any
    exception raised while polling, including deadline or dispatcher cancellation,
    cancels the spawn task, waits for its process group to be reaped, and then
    propagates unchanged. A cancellation that arrives while the watchdog's own kill is
    being reaped propagates after cleanup, and a kill whose terminate-and-reap failed
    re-raises that failure instead of reporting a clean kill.
    """

    spawn_task = asyncio.create_task(_spawn(cmd, stdin_text, log_path, cwd=cwd))
    last_size = _log_size(log_path)
    last_growth = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({spawn_task}, timeout=_WATCHDOG_POLL_SECONDS)
            if done:
                return spawn_task.result()
            size = _log_size(log_path)
            now = time.monotonic()
            if size != last_size:
                last_size = size
                last_growth = now
            elif now - last_growth >= no_output_seconds:
                break
    except BaseException:
        spawn_task.cancel()
        await _await_cancelled_spawn(spawn_task)
        # The original exception is the classification; a cleanup failure is retrieved
        # here so it is not reported as an unretrieved task exception.
        _spawn_cleanup_error(spawn_task)
        raise
    state.fired = True
    spawn_task.cancel()
    interrupted = await _await_cancelled_spawn(spawn_task)
    cleanup_error = _spawn_cleanup_error(spawn_task)
    if interrupted:
        raise asyncio.CancelledError
    if cleanup_error is not None:
        raise cleanup_error
    return None


def validate_output(lane: Lane, raw: object) -> RuntimeLaneOutput:
    """Validate the common output model and the lane-specific closed rule enum."""

    output = RuntimeLaneOutput.model_validate(raw)
    prefix = lane.rules[0].split("/", maxsplit=1)[0]
    allowed_rule_ids = {*lane.rules, f"{prefix}/other"}
    if any(finding.rule_id not in allowed_rule_ids for finding in output.findings):
        raise ValueError("finding rule_id is outside the lane rule enum")
    return output


def _replica_from_run_dir(run_dir: Path) -> int:
    match = _REPLICA_DIRECTORY.fullmatch(run_dir.name)
    if match is None:
        raise ValueError("run_dir must end in an r<replica> directory")
    return int(match.group(1))


class CodexRuntime:
    name: str

    def __init__(
        self,
        *,
        policy: CodexRuntimePolicy = DEFAULT_CODEX_RUNTIME_POLICY,
        mode: CodexRuntimeMode = CodexRuntimeMode.AGENTIC,
        no_output_seconds: int = DEFAULT_NO_OUTPUT_SECONDS,
    ) -> None:
        if no_output_seconds < 1:
            raise ValueError("no_output_seconds must be at least 1")
        self.policy = policy
        self.mode = mode
        self.no_output_seconds = no_output_seconds
        self.name = f"codex-exec-{self.mode}"

    def _mode_command_args(self) -> tuple[str, ...]:
        if self.mode is CodexRuntimeMode.AGENTIC:
            return (
                "-c",
                "features.multi_agent=false",
                "-c",
                "features.collaboration_modes=false",
            )
        args: list[str] = []
        for feature in _TOOL_LESS_DISABLED_FEATURES:
            args.extend(("--disable", feature))
        args.extend(
            (
                "--ignore-rules",
                "--ephemeral",
                "-c",
                'web_search="disabled"',
                "-c",
                "allow_login_shell=false",
            )
        )
        return tuple(args)

    def _usage(
        self,
        *,
        status: RunUsageStatus,
        started: float,
        log_path: Path,
    ) -> RunUsage:
        log_text: str | None
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = None
        marker = _CLI_TOKENS_USED.search(log_text or "")
        cli_tokens_used = int(marker.group(1).replace(",", "")) if marker is not None else None
        # Telemetry only: an unreadable log leaves the counts unknown, except that a
        # tool-less run can never have issued a tool command.
        counts = count_runtime_log_turns(log_text) if log_text is not None else None
        tool_less = self.mode is CodexRuntimeMode.TOOL_LESS
        if tool_less:
            tool_calls: int | None = 0
        else:
            tool_calls = counts.tool_calls if counts is not None else None
        assistant_messages = counts.assistant_messages if counts is not None else None
        return RunUsage(
            model=self.policy.model,
            reasoning_effort=self.policy.reasoning_effort,
            reasoning_summary=self.policy.reasoning_summary,
            no_output_seconds=self.no_output_seconds,
            runtime_mode=self.mode,
            status=status,
            wall_seconds=time.perf_counter() - started,
            cli_tokens_used=cli_tokens_used,
            turns=1 if tool_less else None,
            tool_calls=tool_calls,
            assistant_messages=assistant_messages,
        )

    @staticmethod
    def _save_usage(run_dir: Path, usage: RunUsage) -> None:
        (run_dir / "usage.json").write_text(
            f"{usage.model_dump_json(indent=2)}\n",
            encoding="utf-8",
        )

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
    ) -> RunResult[RuntimeLaneOutput]:
        result = await self.execute_raw(
            schema=lane.output_schema(),
            prompt=prompt,
            run_dir=run_dir,
            deadline_seconds=deadline_seconds,
            workdir=workdir,
            validate=lambda raw: validate_output(lane, raw),
        )
        if result.status is RunStatus.VALID:
            return RunResult(
                lane_id=lane.id,
                replica=result.replica,
                status=result.status,
                output=cast(RuntimeLaneOutput, result.output),
                invalid_reason=None,
                wall_seconds=result.wall_seconds,
                artifact_dir=result.artifact_dir,
                diagnostic=None,
                usage=result.usage,
            )
        return RunResult(
            lane_id=lane.id,
            replica=result.replica,
            status=result.status,
            output=None,
            invalid_reason=result.invalid_reason,
            wall_seconds=result.wall_seconds,
            artifact_dir=result.artifact_dir,
            diagnostic=result.diagnostic,
            usage=result.usage,
        )

    async def execute_raw(
        self,
        *,
        schema: dict[str, Any],
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
        validate: Callable[[object], BaseModel],
    ) -> RunResult[BaseModel]:
        if deadline_seconds < 1:
            raise ValueError("deadline_seconds must be at least 1")
        replica = _replica_from_run_dir(run_dir)
        run_id = run_dir.parent.name

        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.md"
        schema_path = run_dir / "schema.json"
        output_path = run_dir / "out.json"
        log_path = run_dir / "run.log"
        prompt_path.write_text(prompt, encoding="utf-8")
        schema_path.write_text(
            json.dumps(schema, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        output_path.unlink(missing_ok=True)

        command = [
            "codex",
            "exec",
            *self.policy.command_args(),
            "--sandbox",
            _sandbox_mode(),
            "--color",
            "never",
            *self._mode_command_args(),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]

        started = time.perf_counter()
        watchdog = _WatchdogState()
        exit_code: int | None
        try:
            exit_code = await asyncio.wait_for(
                _spawn_with_watchdog(
                    command,
                    prompt,
                    log_path,
                    cwd=workdir,
                    no_output_seconds=self.no_output_seconds,
                    state=watchdog,
                ),
                timeout=deadline_seconds,
            )
        except asyncio.CancelledError:
            self._save_usage(
                run_dir,
                self._usage(
                    status=RunUsageStatus.CANCELED,
                    started=started,
                    log_path=log_path,
                ),
            )
            raise
        except TimeoutError:
            if not watchdog.fired:
                return self._invalid_result(
                    run_id=run_id,
                    replica=replica,
                    reason="exit_nonzero:124",
                    started=started,
                    run_dir=run_dir,
                    log_path=log_path,
                )
            # The watchdog fired first; the deadline only expired while its kill was reaped.
            exit_code = None
        except OSError as error:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason=f"spawn_error:{type(error).__name__}",
                detail=f"{type(error).__name__}: {error}",
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )

        if exit_code is None:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason=f"{NO_OUTPUT_REASON_PREFIX}{self.no_output_seconds}s",
                detail=(
                    f"run.log did not grow for {self.no_output_seconds}s "
                    f"(last size {_log_size(log_path)} bytes)"
                ),
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )
        if exit_code != 0:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason=f"exit_nonzero:{exit_code}",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )
        if not output_path.is_file():
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="missing",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )
        if output_path.stat().st_size == 0:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="empty",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )

        try:
            raw: object = json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="unparseable",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )

        try:
            output = validate(raw)
        except (ValidationError, ValueError):
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="schema-invalid",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )

        try:
            completed = _COMPLETION_MARKER in log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            completed = False
        if not completed:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="no_completion_marker",
                exit_code=exit_code,
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )

        usage = self._usage(
            status=RunUsageStatus.COMPLETED,
            started=started,
            log_path=log_path,
        )
        self._save_usage(run_dir, usage)
        return RunResult(
            lane_id=run_id,
            replica=replica,
            status=RunStatus.VALID,
            output=output,
            invalid_reason=None,
            wall_seconds=usage.wall_seconds,
            artifact_dir=run_dir,
            usage=usage,
        )

    def _invalid_result(
        self,
        *,
        run_id: str,
        replica: int,
        reason: str,
        started: float,
        run_dir: Path,
        log_path: Path,
        exit_code: int | None = None,
        detail: str | None = None,
    ) -> RunResult[BaseModel]:
        output_path = run_dir / "out.json"
        usage = self._usage(
            status=RunUsageStatus.INVALID,
            started=started,
            log_path=log_path,
        )
        self._save_usage(run_dir, usage)
        return RunResult(
            lane_id=run_id,
            replica=replica,
            status=RunStatus.INVALID,
            output=None,
            invalid_reason=reason,
            wall_seconds=usage.wall_seconds,
            artifact_dir=run_dir,
            diagnostic=RunDiagnostic(
                exit_code=exit_code,
                detail=detail,
                log_path=str(log_path),
                log_bytes=log_path.stat().st_size if log_path.is_file() else None,
                output_path=str(output_path),
                output_bytes=output_path.stat().st_size if output_path.is_file() else None,
            ),
            usage=usage,
        )


__all__: list[str] = [
    "DEFAULT_NO_OUTPUT_SECONDS",
    "NO_OUTPUT_REASON_PREFIX",
    "NO_OUTPUT_SECONDS_ENV",
    "REVIEW_PHASE_ENVIRONMENT",
    "CodexRuntime",
    "CodexRuntimeMode",
    "RuntimeLogCounts",
    "count_runtime_log_turns",
    "resolve_no_output_seconds",
    "review_phase_environment",
    "validate_output",
]
