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
from collections.abc import Callable
from contextlib import suppress
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


class CodexRuntimeMode(StrEnum):
    """The evidence and tool boundary for one Codex execution."""

    TOOL_LESS = "tool-less"
    AGENTIC = "agentic"


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


async def _spawn(
    cmd: list[str], stdin_text: str, log_path: Path, *, cwd: Path | None = None
) -> int:
    """Run a command without a shell and combine its output in one log."""

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
    ) -> None:
        self.policy = policy
        self.mode = mode
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
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        marker = _CLI_TOKENS_USED.search(log_text)
        cli_tokens_used = int(marker.group(1).replace(",", "")) if marker is not None else None
        return RunUsage(
            model=self.policy.model,
            reasoning_effort=self.policy.reasoning_effort,
            runtime_mode=self.mode,
            status=status,
            wall_seconds=time.perf_counter() - started,
            cli_tokens_used=cli_tokens_used,
            turns=1 if self.mode is CodexRuntimeMode.TOOL_LESS else None,
            tool_calls=0 if self.mode is CodexRuntimeMode.TOOL_LESS else None,
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
    ) -> RunResult[RuntimeLaneOutput]:
        result = await self.execute_raw(
            schema=lane.output_schema(),
            prompt=prompt,
            run_dir=run_dir,
            deadline_seconds=deadline_seconds,
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
            "read-only",
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
        try:
            exit_code = await asyncio.wait_for(
                _spawn(command, prompt, log_path, cwd=workdir),
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
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="exit_nonzero:124",
                started=started,
                run_dir=run_dir,
                log_path=log_path,
            )
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


__all__: list[str] = ["CodexRuntime", "CodexRuntimeMode", "validate_output"]
