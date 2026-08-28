"""Runtime contracts for executing review lanes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rvw.lane import Lane
from rvw.schema import RuntimeLaneOutput


class RunStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class RunDiagnostic(BaseModel):
    """Inspectable process and artifact facts retained for an invalid execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int | None = None
    detail: str | None = None
    log_path: str | None = None
    log_bytes: int | None = Field(default=None, ge=0)
    output_path: str | None = None
    output_bytes: int | None = Field(default=None, ge=0)


class RunUsageStatus(StrEnum):
    COMPLETED = "completed"
    INVALID = "invalid"
    CANCELED = "canceled"


class RunUsage(BaseModel):
    """Best-effort runtime telemetry that never affects validity."""

    model_config = ConfigDict(extra="forbid")

    model: str
    reasoning_effort: str
    runtime_mode: str | None = None
    status: RunUsageStatus
    wall_seconds: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cli_tokens_used: int | None = Field(default=None, ge=0)
    turns: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class RunResult[OutputT: BaseModel]:
    lane_id: str
    replica: int
    status: RunStatus
    output: OutputT | None
    invalid_reason: str | None
    wall_seconds: float
    artifact_dir: Path
    chunk: int = 1
    diagnostic: RunDiagnostic | None = None
    usage: RunUsage | None = None

    def __post_init__(self) -> None:
        if self.replica < 1:
            raise ValueError("replica must be at least 1")
        if self.chunk < 1:
            raise ValueError("chunk must be at least 1")
        if self.wall_seconds < 0:
            raise ValueError("wall_seconds must not be negative")
        if self.status is RunStatus.VALID:
            if (
                self.output is None
                or self.invalid_reason is not None
                or self.diagnostic is not None
            ):
                raise ValueError(
                    "VALID results require output, no invalid_reason, and no diagnostic"
                )
        elif (
            self.output is not None
            or self.invalid_reason is None
            or not self.invalid_reason.strip()
        ):
            raise ValueError("INVALID results require invalid_reason and no output")


class Runtime(Protocol):
    name: str

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
    ) -> RunResult[RuntimeLaneOutput]: ...

    async def execute_raw(
        self,
        *,
        schema: dict[str, Any],
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
        validate: Callable[[object], BaseModel],
    ) -> RunResult[BaseModel]: ...


__all__: list[str] = [
    "RunDiagnostic",
    "RunResult",
    "RunStatus",
    "RunUsage",
    "RunUsageStatus",
    "Runtime",
]
