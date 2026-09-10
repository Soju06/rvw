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
    publish:
      on_block: comment
      on_pass: comment
      dismiss_on_pass: false
      approve_requires_explicit_opt_in: true
    threads:
      resolve_on_fix: true
      reuse_open_thread: true

``publish_state`` accepts only ``comment`` or ``none`` and supplies the legacy
channel default: ``none`` means checks-only unless explicit channels override it.
The ``publish`` block selects the GitHub review event per verdict and the
``threads`` block governs rvw's own inline
threads; both default to the historical COMMENT-only behaviour. ``approve`` is
double-gated: it requires ``approve_requires_explicit_opt_in: false`` in the same
file. Any invalid value in either block fails closed as ``publish_policy_invalid``.
"""

from __future__ import annotations

import subprocess
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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


class PublishPolicyInvalid(ValueError):
    """The ``publish`` or ``threads`` block cannot be trusted; publication must not run."""

    reason = "publish_policy_invalid"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.reason}: {detail}")


ReviewEventOnBlock = Literal["comment", "request_changes"]
ReviewEventOnPass = Literal["comment", "approve", "none"]
PublishPolicySource = Literal["default", "repository", "explicit"]
PublishChannel = Literal["checks", "review"]


class CheckPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    on_block: Literal["failure", "neutral"] = "failure"
    on_pass: Literal["success", "neutral"] = "success"


class InlinePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    severity_at_least: Literal["suggestion", "warning", "blocker"] = "suggestion"
    max_comments: int | None = Field(default=None, ge=0)


class PublishPolicy(BaseModel):
    """Which GitHub review event each policy verdict publishes."""

    model_config = ConfigDict(extra="forbid", strict=True)

    channels: list[PublishChannel] = Field(default=["checks", "review"], min_length=1)
    checks: CheckPolicy = Field(default_factory=CheckPolicy)
    inline: InlinePolicy = Field(default_factory=InlinePolicy)
    on_block: ReviewEventOnBlock = "comment"
    on_pass: ReviewEventOnPass = "comment"
    dismiss_on_pass: bool = False
    approve_requires_explicit_opt_in: bool = True

    @model_validator(mode="after")
    def _approve_is_double_gated(self) -> PublishPolicy:
        if self.on_pass == "approve" and self.approve_requires_explicit_opt_in:
            raise ValueError("approve_not_opted_in")
        return self


class ThreadPolicy(BaseModel):
    """How rvw treats its own inline review threads across heads."""

    model_config = ConfigDict(extra="forbid", strict=True)

    resolve_on_fix: bool = True
    reuse_open_thread: bool = True


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
    allow_language_fallback: bool = Field(default=False, strict=True)
    publish: PublishPolicy = Field(default_factory=PublishPolicy)
    threads: ThreadPolicy = Field(default_factory=ThreadPolicy)

    @model_validator(mode="after")
    def _legacy_publication_channels(self) -> AutoPolicy:
        if "channels" not in self.publish.model_fields_set and self.publish_state == "none":
            self.publish = self.publish.model_copy(update={"channels": ["checks"]})
        return self


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


def _publish_block_detail(error: Mapping[str, Any]) -> str:
    message = str(error.get("msg", ""))
    if "approve_not_opted_in" in message:
        return "approve_not_opted_in"
    location = ".".join(str(part) for part in error.get("loc", ()))
    return f"{location}: {message}"


def validate_policy(raw: object) -> AutoPolicy:
    """Validate a policy document, naming ``publish``/``threads`` faults distinctly.

    Faults inside the two publication blocks are raised as ``PublishPolicyInvalid`` so the
    process contract records ``publish_policy_invalid``; every other schema violation stays an
    ordinary ``ValidationError`` (``invalid_policy``).
    """

    try:
        return AutoPolicy.model_validate(raw)
    except ValidationError as exc:
        publication_errors = [
            error
            for error in exc.errors()
            if error.get("loc") and error["loc"][0] in {"publish", "threads"}
        ]
        if publication_errors:
            raise PublishPolicyInvalid(_publish_block_detail(publication_errors[0])) from exc
        raise


def repository_policy_from_contents(raw: object) -> AutoPolicy | None:
    """Validate a repository ``auto.yaml`` fetched through the GitHub contents API.

    ``raw`` is the decoded response; ``None`` means the file is absent. Malformed content
    raises like any other selected source.
    """

    import base64

    if not isinstance(raw, Mapping):
        return None
    content = raw.get("content")
    if raw.get("type") != "file" or not isinstance(content, str):
        return None
    text = base64.b64decode("".join(content.split())).decode("utf-8")
    return validate_policy(yaml.safe_load(text))


def packaged_policy() -> EffectivePolicy:
    """The packaged default policy, used when no trustworthy source is reachable."""

    resource_path = "resources/policies/auto-default.yaml"
    default = files("rvw").joinpath(resource_path).read_text(encoding="utf-8")
    return EffectivePolicy(
        validate_policy(yaml.safe_load(default)), "package", f"rvw:{resource_path}"
    )


def publish_policy_source(source: str) -> PublishPolicySource:
    """Collapse effective-policy provenance to the recorded ``publish.policy_source``."""

    if source == "repository":
        return "repository"
    if source == "explicit":
        return "explicit"
    return "default"


def load_policy(path: Path) -> AutoPolicy:
    """Load and strictly validate one YAML auto policy."""

    expanded = path.expanduser()
    if not expanded.is_file():
        raise PolicyNotFound(expanded)
    return validate_policy(yaml.safe_load(expanded.read_text(encoding="utf-8")))


def resolve_auto_policy(
    target: ResolvedTarget,
    *,
    cwd: Path,
    policy: str | Path = "auto",
    external_path: Path | None = None,
    allow_external: bool = True,
) -> EffectivePolicy:
    """Select explicit, immutable repository, legacy external, then packaged policy.

    Only a missing source permits fallback. Invalid YAML or a schema violation
    in the selected source must reach the caller as an invalid configuration.
    ``allow_external=False`` skips the deprecated external file, which publication-time
    resolution never trusts.
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
            selected = validate_policy(yaml.safe_load(raw))
            return EffectivePolicy(selected, "repository", repository_path)

    external = (external_path or Path("~/.hermes/review/policies/auto.yaml")).expanduser()
    if not external.is_absolute():
        external = cwd / external
    if allow_external and external.is_file():
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
        validate_policy(yaml.safe_load(default)), "package", f"rvw:{resource_path}"
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
    "PublishPolicy",
    "PublishPolicyInvalid",
    "PublishPolicySource",
    "ReviewEventOnBlock",
    "ReviewEventOnPass",
    "ThreadPolicy",
    "evaluate",
    "load_policy",
    "packaged_policy",
    "publish_policy_source",
    "repository_policy_from_contents",
    "resolve_auto_policy",
    "validate_policy",
]
