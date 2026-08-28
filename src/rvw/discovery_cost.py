"""Pure preflight accounting and acknowledgement rules for DISCOVER."""

from __future__ import annotations

from dataclasses import dataclass

from rvw.discover import DiscoveryPlan
from rvw.runtime_policy import CodexRuntimePolicy

DEFAULT_MAX_DISCOVERY_RUNS = 12


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
        return {
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


def build_discovery_preflight(
    plan: DiscoveryPlan,
    *,
    replicas: int,
    max_discovery_runs: int,
    runtime_policy: CodexRuntimePolicy,
) -> DiscoveryPreflight:
    """Summarize exact initial prompts and bounded retry work for a plan."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")
    if max_discovery_runs < 1:
        raise ValueError("max_discovery_runs must be at least 1")

    reasons: list[str] = []
    if replicas >= 2:
        reasons.append(f"discovery_replicas={replicas}")
    if plan.retry_upper_bound > max_discovery_runs:
        reasons.append(
            "retry_upper_bound="
            f"{plan.retry_upper_bound} exceeds max_discovery_runs={max_discovery_runs}"
        )
    if runtime_policy.reasoning_effort == "max":
        reasons.append("reasoning_effort=max")
    return DiscoveryPreflight(
        lanes=len({run.lane.id for run in plan.runs}),
        replicas=replicas,
        chunks=len({run.chunk for run in plan.runs}),
        initial_runs=plan.initial_runs,
        retry_upper_bound=plan.retry_upper_bound,
        initial_prompt_characters=plan.initial_prompt_characters,
        max_discovery_runs=max_discovery_runs,
        runtime_policy=runtime_policy,
        heavy_discovery_reasons=tuple(reasons),
    )


__all__ = [
    "DEFAULT_MAX_DISCOVERY_RUNS",
    "DiscoveryPreflight",
    "build_discovery_preflight",
]
