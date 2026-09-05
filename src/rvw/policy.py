"""Deterministic auto-mode policy evaluation (ADR-009).

Policy files use this YAML shape::

    promote_to_blocker:
      agreement_at_least: 2
      severity_at_least: warning
    drop:
      agreement_at_most: 1
      severity_at_most: suggestion
    block_when:
      severity_at_least: blocker
      confirmed_only: true
    publish_state: comment

``publish_state`` accepts only ``comment`` or ``none``. Approval is
intentionally not expressible by policy.
"""

from __future__ import annotations

import subprocess
import warnings
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rvw.adjudicate import AdjudicationOutcome
from rvw.merge import MergeResult
from rvw.schema import Severity, Verdict
from rvw.target import ResolvedTarget

_SEVERITY_RANK = {
    Severity.SUGGESTION: 1,
    Severity.WARNING: 2,
    Severity.BLOCKER: 3,
}


class PolicyNotFound(FileNotFoundError):
    """The requested auto policy file does not exist."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"auto policy not found: {path}")


class PromoteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_at_least: int = Field(ge=1)
    severity_at_least: Severity


class DropRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_at_most: int = Field(ge=0)
    severity_at_most: Severity


class BlockRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity_at_least: Severity
    confirmed_only: bool = True


class AutoPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promote_to_blocker: PromoteRule
    drop: DropRule
    block_when: BlockRule
    publish_state: Literal["comment", "none"]


class AutoDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "BLOCK"]
    blocking: list[str]
    dropped: list[str]
    promoted: list[str]
    considered: int


@dataclass(frozen=True)
class EffectivePolicy:
    """The selected policy and reproducible provenance for the process contract."""

    policy: AutoPolicy
    source: Literal["explicit", "repository", "external", "package"]
    path: str


def load_policy(path: Path) -> AutoPolicy:
    """Load and strictly validate one YAML auto policy."""

    expanded = path.expanduser()
    if not expanded.is_file():
        raise PolicyNotFound(expanded)
    return AutoPolicy.model_validate(yaml.safe_load(expanded.read_text(encoding="utf-8")))


def resolve_auto_policy(
    target: ResolvedTarget,
    *,
    cwd: Path,
    policy: str | Path = "auto",
    external_path: Path | None = None,
) -> EffectivePolicy:
    """Select explicit, immutable repository, legacy external, then packaged policy.

    Only a missing source permits fallback. Invalid YAML or a schema violation
    in the selected source must reach the caller as an invalid configuration.
    """

    if str(policy) != "auto":
        explicit = Path(policy).expanduser()
        if not explicit.is_absolute():
            explicit = cwd / explicit
        return EffectivePolicy(load_policy(explicit), "explicit", str(explicit))

    if target.base_sha is not None:
        repository_path = f"{target.base_sha}:.rvw/policies/auto.yaml"
        try:
            raw = subprocess.run(
                ["git", "show", repository_path],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except subprocess.CalledProcessError:
            pass
        else:
            selected = AutoPolicy.model_validate(yaml.safe_load(raw))
            return EffectivePolicy(selected, "repository", repository_path)

    external = (external_path or Path("~/.hermes/review/policies/auto.yaml")).expanduser()
    if not external.is_absolute():
        external = cwd / external
    if external.is_file():
        warnings.warn(
            f"external auto policy is deprecated: {external}; "
            "move it to .rvw/policies/auto.yaml or pass --policy explicitly",
            FutureWarning,
            stacklevel=2,
        )
        return EffectivePolicy(load_policy(external), "external", str(external))

    resource_path = "resources/policies/auto-default.yaml"
    default = files("rvw").joinpath(resource_path).read_text(encoding="utf-8")
    return EffectivePolicy(
        AutoPolicy.model_validate(yaml.safe_load(default)), "package", f"rvw:{resource_path}"
    )


def _at_least(value: Severity, threshold: Severity) -> bool:
    return _SEVERITY_RANK[value] >= _SEVERITY_RANK[threshold]


def _at_most(value: Severity, threshold: Severity) -> bool:
    return _SEVERITY_RANK[value] <= _SEVERITY_RANK[threshold]


def evaluate(
    policy: AutoPolicy,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
) -> AutoDecision:
    """Evaluate merged groups without model calls or external I/O."""

    unresolved = set(outcome.unresolved) if outcome is not None else set()
    blocking: list[str] = []
    dropped: list[str] = []
    promoted: list[str] = []
    considered = 0

    for group in merged.groups:
        if outcome is None or group.key in unresolved:
            group_verdict = Verdict.UNCERTAIN
        else:
            group_verdict = outcome.verdicts.get(group.key, Verdict.UNCERTAIN)

        if group_verdict is Verdict.REJECTED:
            continue

        drop_rule = policy.drop
        if group.agreement <= drop_rule.agreement_at_most and _at_most(
            group.severity, drop_rule.severity_at_most
        ):
            dropped.append(group.key)
            continue

        considered += 1
        effective_severity = group.severity
        promote_rule = policy.promote_to_blocker
        if (
            group.severity is not Severity.BLOCKER
            and group.agreement >= promote_rule.agreement_at_least
            and _at_least(group.severity, promote_rule.severity_at_least)
        ):
            effective_severity = Severity.BLOCKER
            promoted.append(group.key)

        block_rule = policy.block_when
        may_block = group_verdict is Verdict.CONFIRMED or not block_rule.confirmed_only
        if may_block and _at_least(effective_severity, block_rule.severity_at_least):
            blocking.append(group.key)

    return AutoDecision(
        verdict="BLOCK" if blocking else "PASS",
        blocking=blocking,
        dropped=dropped,
        promoted=promoted,
        considered=considered,
    )


__all__ = [
    "AutoDecision",
    "AutoPolicy",
    "BlockRule",
    "DropRule",
    "EffectivePolicy",
    "PolicyNotFound",
    "PromoteRule",
    "evaluate",
    "load_policy",
    "resolve_auto_policy",
]
