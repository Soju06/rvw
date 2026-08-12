"""Read-only ``codex exec`` runtime adapter."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from rvw.lane import Lane
from rvw.runtimes import RunResult, RunStatus
from rvw.schema import RuntimeLaneOutput

_REPLICA_DIRECTORY = re.compile(r"r([1-9][0-9]*)")
_COMPLETION_MARKER = "tokens used"
_PROCESS_TERMINATION_TIMEOUT_SECONDS = 5
_SETPRIV = shutil.which("setpriv") if sys.platform.startswith("linux") else None


async def _terminate_and_reap(process: asyncio.subprocess.Process) -> None:
    """Terminate a started subprocess, escalating to SIGKILL after a bounded wait."""

    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def _cleanup_before_unwind(process: asyncio.subprocess.Process) -> None:
    """Finish subprocess cleanup even if the awaiting task is cancelled again."""

    cleanup = asyncio.create_task(_terminate_and_reap(process))
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
        )
        try:
            await process.communicate(stdin_text.encode("utf-8"))
        except BaseException:
            await _cleanup_before_unwind(process)
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
    name = "codex-exec-ro"

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
            )
        return RunResult(
            lane_id=lane.id,
            replica=result.replica,
            status=result.status,
            output=None,
            invalid_reason=result.invalid_reason,
            wall_seconds=result.wall_seconds,
            artifact_dir=result.artifact_dir,
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
            "timeout",
            "--foreground",
            "--signal=TERM",
            "--kill-after=30s",
            f"{deadline_seconds}s",
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
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]

        started = time.perf_counter()
        try:
            exit_code = await _spawn(command, prompt, log_path, cwd=workdir)
        except OSError as error:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason=f"spawn_error:{type(error).__name__}",
                started=started,
                run_dir=run_dir,
            )

        if exit_code != 0:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason=f"exit_nonzero:{exit_code}",
                started=started,
                run_dir=run_dir,
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="missing_artifact",
                started=started,
                run_dir=run_dir,
            )

        try:
            raw: object = json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="json_parse_error",
                started=started,
                run_dir=run_dir,
            )

        try:
            output = validate(raw)
        except (ValidationError, ValueError):
            return self._invalid_result(
                run_id=run_id,
                replica=replica,
                reason="schema_validation_error",
                started=started,
                run_dir=run_dir,
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
                started=started,
                run_dir=run_dir,
            )

        return RunResult(
            lane_id=run_id,
            replica=replica,
            status=RunStatus.VALID,
            output=output,
            invalid_reason=None,
            wall_seconds=time.perf_counter() - started,
            artifact_dir=run_dir,
        )

    @staticmethod
    def _invalid_result(
        *,
        run_id: str,
        replica: int,
        reason: str,
        started: float,
        run_dir: Path,
    ) -> RunResult[BaseModel]:
        return RunResult(
            lane_id=run_id,
            replica=replica,
            status=RunStatus.INVALID,
            output=None,
            invalid_reason=reason,
            wall_seconds=time.perf_counter() - started,
            artifact_dir=run_dir,
        )


__all__: list[str] = ["CodexRuntime", "validate_output"]
