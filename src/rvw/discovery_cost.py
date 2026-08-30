"""Pure preflight accounting and acknowledgement rules for DISCOVER."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rvw.discover import DiscoveryPlan
from rvw.runtime_policy import CodexRuntimePolicy

DEFAULT_MAX_DISCOVERY_RUNS = 12


class _RuntimePreflightPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)

    @field_validator("model", "reasoning_effort")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("runtime preflight values must be non-empty")
        return value


class _DiscoveryPreflightPayload(BaseModel):
    """Strict persisted representation of a known DISCOVER cost."""

    model_config = ConfigDict(extra="forbid", strict=True)

    lane_count: int = Field(ge=0)
    replicas: int = Field(ge=1)
    chunks: int = Field(ge=0)
    initial_runs: int = Field(ge=0)
    retry_upper_bound: int = Field(ge=0)
    initial_prompt_characters: int = Field(ge=0)
    max_discovery_runs: int = Field(ge=1)
    runtime: _RuntimePreflightPayload
    requires_allow_heavy_discovery: bool
    heavy_discovery_reasons: list[str]

    @field_validator("heavy_discovery_reasons")
    @classmethod
    def _reasons_are_nonempty(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("heavy discovery reasons must be non-empty")
        return values

    @model_validator(mode="after")
    def _totals_and_acknowledgement_are_consistent(self) -> _DiscoveryPreflightPayload:
        if self.retry_upper_bound != self.initial_runs * 2:
            raise ValueError("retry_upper_bound must equal twice initial_runs")
        if self.initial_runs % self.replicas:
            raise ValueError("initial_runs must be divisible by replicas")
        if self.initial_runs and (not self.lane_count or not self.chunks):
            raise ValueError("nonzero initial_runs require lanes and chunks")
        if self.initial_runs < self.lane_count * self.replicas:
            raise ValueError("initial_runs must cover every lane replica")
        if self.initial_runs < self.chunks * self.replicas:
            raise ValueError("initial_runs must cover every chunk replica")

        expected_reasons: list[str] = []
        if self.replicas >= 2:
            expected_reasons.append(f"discovery_replicas={self.replicas}")
        if self.retry_upper_bound > self.max_discovery_runs:
            expected_reasons.append(
                "retry_upper_bound="
                f"{self.retry_upper_bound} exceeds max_discovery_runs={self.max_discovery_runs}"
            )
        legacy_reasons = [*expected_reasons, "reasoning_effort=max"]
        if self.heavy_discovery_reasons == legacy_reasons:
            # Runs persisted before max effort became an informational profile
            # recorded this obsolete acknowledgement reason. Normalize it while
            # loading so their resume preflight can still match the new policy.
            self.heavy_discovery_reasons = expected_reasons
            self.requires_allow_heavy_discovery = bool(expected_reasons)
        elif self.heavy_discovery_reasons != expected_reasons:
            raise ValueError("heavy_discovery_reasons do not match preflight totals and runtime")
        if self.requires_allow_heavy_discovery != bool(expected_reasons):
            raise ValueError(
                "requires_allow_heavy_discovery does not match heavy discovery reasons"
            )
        return self


def validate_discovery_preflight_payload(payload: object) -> dict[str, object]:
    """Validate and normalize one persisted discovery preflight payload."""

    validated = _DiscoveryPreflightPayload.model_validate(payload)
    return cast(dict[str, object], validated.model_dump(mode="json"))


@dataclass(frozen=True, slots=True)
class DiscoveryPreflight:
    """Known discovery cost before a runtime execution begins."""

    lanes: int
    replicas: int
    chunks: int
    initial_runs: int
    retry_upper_bound: int
    initial_prompt_characters: int
    max_discovery_runs: int
    runtime_policy: CodexRuntimePolicy
    heavy_discovery_reasons: tuple[str, ...]

    @property
    def requires_allow_heavy_discovery(self) -> bool:
        return bool(self.heavy_discovery_reasons)

    def payload(self) -> dict[str, object]:
        return validate_discovery_preflight_payload(
            {
                "lane_count": self.lanes,
                "replicas": self.replicas,
                "chunks": self.chunks,
                "initial_runs": self.initial_runs,
                "retry_upper_bound": self.retry_upper_bound,
                "initial_prompt_characters": self.initial_prompt_characters,
                "max_discovery_runs": self.max_discovery_runs,
                "runtime": self.runtime_policy.payload(),
                "requires_allow_heavy_discovery": self.requires_allow_heavy_discovery,
                "heavy_discovery_reasons": list(self.heavy_discovery_reasons),
            }
        )


class DiscoveryCostError(ValueError):
    """Raised before runtime work when the selected plan needs acknowledgement."""

    def __init__(self, preflight: DiscoveryPreflight) -> None:
        self.preflight = preflight
        reasons = ", ".join(preflight.heavy_discovery_reasons)
        super().__init__(f"discovery plan requires --allow-heavy-discovery ({reasons})")

    def payload(self) -> dict[str, object]:
        return {
            "error": "heavy-discovery-acknowledgement-required",
            "message": str(self),
            "preflight": self.preflight.payload(),
        }


def _build_discovery_preflight(
    *,
    lanes: int,
    chunks: int,
    initial_runs: int,
    initial_prompt_characters: int,
    replicas: int,
    max_discovery_runs: int,
    runtime_policy: CodexRuntimePolicy,
) -> DiscoveryPreflight:
    """Build a preflight from exact planned-work totals."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")
    if max_discovery_runs < 1:
        raise ValueError("max_discovery_runs must be at least 1")

    retry_upper_bound = initial_runs * 2
    reasons: list[str] = []
    if replicas >= 2:
        reasons.append(f"discovery_replicas={replicas}")
    if retry_upper_bound > max_discovery_runs:
        reasons.append(
            f"retry_upper_bound={retry_upper_bound} exceeds max_discovery_runs={max_discovery_runs}"
        )
    return DiscoveryPreflight(
        lanes=lanes,
        replicas=replicas,
        chunks=chunks,
        initial_runs=initial_runs,
        retry_upper_bound=retry_upper_bound,
        initial_prompt_characters=initial_prompt_characters,
        max_discovery_runs=max_discovery_runs,
        runtime_policy=runtime_policy,
        heavy_discovery_reasons=tuple(reasons),
    )


def build_discovery_preflight(
    plan: DiscoveryPlan,
    *,
    replicas: int,
    max_discovery_runs: int,
    runtime_policy: CodexRuntimePolicy,
) -> DiscoveryPreflight:
    """Summarize exact initial prompts and bounded retry work for a plan."""

    if plan.replicas != replicas:
        raise ValueError(
            "planned discovery replicas "
            f"({plan.replicas}) must match requested replicas ({replicas})"
        )
    return _build_discovery_preflight(
        lanes=len({run.lane.id for run in plan.runs}),
        chunks=len({run.chunk for run in plan.runs}),
        initial_runs=plan.initial_runs,
        initial_prompt_characters=plan.initial_prompt_characters,
        replicas=replicas,
        max_discovery_runs=max_discovery_runs,
        runtime_policy=runtime_policy,
    )


def build_stack_discovery_preflight(
    plans: Sequence[DiscoveryPlan],
    *,
    replicas: int,
    max_discovery_runs: int,
    runtime_policy: CodexRuntimePolicy,
) -> DiscoveryPreflight:
    """Aggregate member plans before a stack starts its first runtime dispatch."""

    if any(plan.replicas != replicas for plan in plans):
        raise ValueError("every planned discovery replica count must match the stack replica count")
    return _build_discovery_preflight(
        lanes=sum(len({run.lane.id for run in plan.runs}) for plan in plans),
        chunks=sum(len({run.chunk for run in plan.runs}) for plan in plans),
        initial_runs=sum(plan.initial_runs for plan in plans),
        initial_prompt_characters=sum(plan.initial_prompt_characters for plan in plans),
        replicas=replicas,
        max_discovery_runs=max_discovery_runs,
        runtime_policy=runtime_policy,
    )


def require_heavy_discovery_acknowledgement(
    preflight: DiscoveryPreflight,
    *,
    allow_heavy_discovery: bool,
) -> None:
    """Fail closed before discovery unless the operator acknowledged known cost."""

    if preflight.requires_allow_heavy_discovery and not allow_heavy_discovery:
        raise DiscoveryCostError(preflight)


__all__ = [
    "DEFAULT_MAX_DISCOVERY_RUNS",
    "DiscoveryCostError",
    "DiscoveryPreflight",
    "build_discovery_preflight",
    "build_stack_discovery_preflight",
    "require_heavy_discovery_acknowledgement",
    "validate_discovery_preflight_payload",
]
