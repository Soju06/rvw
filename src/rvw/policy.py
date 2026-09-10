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

import fnmatch
import re
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


def _validate_title_regex(pattern: str) -> None:
    """Reject syntax whose Python and JavaScript meanings differ."""
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index >= len(pattern):
                raise ValueError("invalid title regex escape")
            escaped = pattern[index]
            if escaped in {"x", "u"}:
                length = 2 if escaped == "x" else 4
                digits = pattern[index + 1 : index + 1 + length]
                if len(digits) != length or re.fullmatch(r"[0-9a-fA-F]+", digits) is None:
                    raise ValueError("invalid title regex character escape")
                if escaped == "u" and 0xD800 <= int(digits, 16) <= 0xDFFF:
                    raise ValueError("surrogate title regex escape is not portable")
                index += length
            elif escaped not in "\\.^$*+?{}[]()|nrtfv" and not (in_class and escaped == "-"):
                raise ValueError("title regex escape is not portable")
        elif char == "[" and not in_class:
            in_class = True
            if pattern[index + 1 : index + 2] == "]" or pattern[index + 1 : index + 3] == "^]":
                raise ValueError("empty title regex character class is not portable")
        elif char == "]":
            if not in_class:
                raise ValueError("literal closing bracket must be escaped")
            in_class = False
        elif not in_class:
            following = pattern[index + 1 : index + 2]
            if (
                char == "("
                and following == "?"
                and pattern[index + 2 : index + 3] not in {":", "=", "!"}
            ):
                raise ValueError("title regex group is not portable")
            if char in "*+?}" and following == "+":
                raise ValueError("possessive title regex quantifier is not portable")
            if char == "{":
                quantifier = re.match(r"\{[0-9]+(?:,[0-9]*)?\}", pattern[index:])
                if quantifier is None:
                    raise ValueError("literal opening brace must be escaped")
                index += len(quantifier.group()) - 1
                if pattern[index + 1 : index + 2] == "+":
                    raise ValueError("possessive title regex quantifier is not portable")
            elif char == "}":
                raise ValueError("literal closing brace must be escaped")
        index += 1
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid title regex: {exc}") from exc


class TriggerRule(BaseModel):
    """One repository-owned pull-request eligibility rule."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[a-z0-9-]+$")
    authors: list[str] | None = None
    head_branches: list[str] | None = None
    base_branches: list[str] | None = None
    labels: list[str] | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _has_match_field(self) -> TriggerRule:
        if not any(
            value is not None
            for value in (
                self.authors,
                self.head_branches,
                self.base_branches,
                self.labels,
                self.title,
            )
        ):
            raise ValueError("trigger rule must contain at least one match field")
        if self.title is not None:
            _validate_title_regex(self.title)
        return self


class TriggerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["denylist", "allowlist"] = "denylist"
    drafts: Literal["skip", "review"] = "skip"
    rules: list[TriggerRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rules_are_usable(self) -> TriggerPolicy:
        names = [rule.name for rule in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("trigger rule names must be unique")
        if self.mode == "allowlist" and not self.rules:
            raise ValueError("allowlist triggers require at least one rule")
        return self


class TriggerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    author: str | None = None
    head_branch: str | None = None
    base_branch: str | None = None
    labels: list[str] = Field(default_factory=list)
    title: str = ""
    draft: bool = False


@dataclass(frozen=True)
class TriggerDecision:
    skipped: bool
    rule: str | None
    mode: Literal["denylist", "allowlist"]


def _rule_matches(rule: TriggerRule, metadata: TriggerMetadata) -> bool:
    if rule.authors is not None and (
        metadata.author is None
        or metadata.author.lower() not in {author.lower() for author in rule.authors}
    ):
        return False
    if rule.head_branches is not None and (
        metadata.head_branch is None
        or not any(
            fnmatch.fnmatchcase(metadata.head_branch, pattern) for pattern in rule.head_branches
        )
    ):
        return False
    if rule.base_branches is not None and (
        metadata.base_branch is None
        or not any(
            fnmatch.fnmatchcase(metadata.base_branch, pattern) for pattern in rule.base_branches
        )
    ):
        return False
    if rule.labels is not None:
        wanted = {label.lower() for label in rule.labels}
        if not any(label.lower() in wanted for label in metadata.labels):
            return False
    return rule.title is None or re.search(rule.title, metadata.title) is not None


def evaluate_trigger(policy: TriggerPolicy, metadata: TriggerMetadata) -> TriggerDecision:
    """Apply repository trigger policy to PR metadata without inspecting its diff."""

    if metadata.draft and policy.drafts == "skip":
        return TriggerDecision(True, None, policy.mode)
    match = next((rule for rule in policy.rules if _rule_matches(rule, metadata)), None)
    if policy.mode == "denylist":
        return TriggerDecision(match is not None, match.name if match else None, policy.mode)
    return TriggerDecision(match is None, match.name if match else None, policy.mode)


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
    triggers: TriggerPolicy = Field(default_factory=TriggerPolicy)

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


class _PolicyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        keys: set[object] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in keys
                keys.add(key)
            except TypeError as exc:
                raise ValueError("auto policy keys must be scalar") from exc
            if duplicate:
                raise ValueError(f"duplicate auto policy key: {key}")
        return super().construct_mapping(node, deep=deep)


def load_policy_yaml(raw: str) -> object:
    """Decode auto policy YAML, rejecting duplicate mapping keys."""
    return yaml.load(raw, Loader=_PolicyLoader)


def _publish_block_detail(error: Mapping[str, Any]) -> str:
    message = str(error.get("msg", ""))
    if "approve_not_opted_in" in message:
        return "approve_not_opted_in"
    location = ".".join(str(part) for part in error.get("loc", ()))
    return f"{location}: {message}"


def validate_policy(raw: object, *, ignore_invalid_triggers: bool = False) -> AutoPolicy:
    """Validate a policy document, naming ``publish``/``threads`` faults distinctly.

    Faults inside the two publication blocks are raised as ``PublishPolicyInvalid`` so the
    process contract records ``publish_policy_invalid``; every other schema violation stays an
    ordinary ``ValidationError`` (``invalid_policy``).
    """

    if ignore_invalid_triggers and isinstance(raw, Mapping) and "triggers" in raw:
        try:
            TriggerPolicy.model_validate(raw["triggers"])
        except ValidationError:
            raw = {**raw, "triggers": {}}
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


def repository_policy_from_contents(
    raw: object, *, ignore_invalid_triggers: bool = False
) -> AutoPolicy | None:
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
    return validate_policy(load_policy_yaml(text), ignore_invalid_triggers=ignore_invalid_triggers)


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


def load_policy(path: Path, *, ignore_invalid_triggers: bool = False) -> AutoPolicy:
    """Load and strictly validate one YAML auto policy."""

    expanded = path.expanduser()
    if not expanded.is_file():
        raise PolicyNotFound(expanded)
    return validate_policy(
        load_policy_yaml(expanded.read_text(encoding="utf-8")),
        ignore_invalid_triggers=ignore_invalid_triggers,
    )


def resolve_auto_policy(
    target: ResolvedTarget,
    *,
    cwd: Path,
    policy: str | Path = "auto",
    external_path: Path | None = None,
    allow_external: bool = True,
    ignore_invalid_triggers: bool = False,
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
        return EffectivePolicy(
            load_policy(explicit, ignore_invalid_triggers=ignore_invalid_triggers),
            "explicit",
            str(explicit),
        )

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
            selected = validate_policy(
                load_policy_yaml(raw), ignore_invalid_triggers=ignore_invalid_triggers
            )
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
    "TriggerDecision",
    "TriggerMetadata",
    "TriggerPolicy",
    "TriggerRule",
    "evaluate",
    "evaluate_trigger",
    "load_policy",
    "load_policy_yaml",
    "packaged_policy",
    "publish_policy_source",
    "repository_policy_from_contents",
    "resolve_auto_policy",
    "validate_policy",
]
