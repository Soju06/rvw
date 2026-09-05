"""Lane document loading and runtime output-schema generation."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier

_SEVERITY_ORDER = (Severity.SUGGESTION, Severity.WARNING, Severity.BLOCKER)


def validate_glob_patterns(patterns: list[str] | None) -> list[str] | None:
    """Reject brace expansion, which is not part of fnmatchcase semantics."""

    for pattern in patterns or ():
        if "{" in pattern or "}" in pattern:
            raise ValueError(
                "unsupported-glob-braces: brace expansion is not supported; list separate patterns"
            )
    return patterns


class LaneActivation(BaseModel):
    """Activation metadata embedded in a new-format lane document."""

    model_config = ConfigDict(extra="forbid")

    paths: list[str] | None = None

    _validate_paths = field_validator("paths")(validate_glob_patterns)


class LaneLintConfig(BaseModel):
    """Typed exceptions for mechanical lane-scope checks."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    allow_scope_terms: list[str] = Field(default_factory=list, alias="allow-scope-terms")

    @field_validator("allow_scope_terms")
    @classmethod
    def _terms_must_be_nonempty(cls, terms: list[str]) -> list[str]:
        if any(not term.strip() for term in terms):
            raise ValueError("lint allow-scope-terms entries must be nonempty")
        return terms


class Lane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(alias="lane")
    tier: Tier
    schedule_hint: Literal["light", "normal", "heavy"] = "normal"
    rules: list[str] = Field(min_length=1)
    when: LaneActivation | None = None
    lint: LaneLintConfig | None = None
    severity_cap: Severity = Severity.BLOCKER
    covered_by_others: Literal["inject"] | None = None
    # Lane lifecycle: "pending" = not yet gated by `rvw sample --compare-free`
    # (ADR-004 verification). None = validated / pre-dates the gate.
    validation: Literal["pending"] | None = None
    prompt_body: str

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_cost(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "cost" in data and "schedule_hint" in data:
            raise ValueError("cost and schedule_hint cannot be used together")
        if "cost" in data:
            data["schedule_hint"] = data.pop("cost")
        return data

    @property
    def cost(self) -> Literal["light", "normal", "heavy"]:
        """Compatibility accessor for callers migrating to ``schedule_hint``."""

        return self.schedule_hint

    def output_schema(self) -> dict[str, Any]:
        """Build the strict, self-contained schema consumed by lane runtimes."""

        schema = RuntimeLaneOutput.model_json_schema()
        schema.pop("$defs")
        runtime_properties = dict(RuntimeFinding.model_json_schema()["properties"])

        prefix = self.rules[0].split("/", maxsplit=1)[0]
        runtime_properties["rule_id"] = {
            "type": "string",
            "enum": [*self.rules, f"{prefix}/other"],
        }
        cap_index = _SEVERITY_ORDER.index(self.severity_cap)
        runtime_properties["severity"] = {
            "type": "string",
            "enum": [severity.value for severity in reversed(_SEVERITY_ORDER[: cap_index + 1])],
        }

        schema["additionalProperties"] = False
        # OpenAI strict structured output requires EVERY object level to list
        # all of its properties in `required` (live 400 otherwise: "'required'
        # is required ... Missing 'findings'"). Pydantic omits defaulted fields.
        schema["required"] = list(schema["properties"])
        schema["properties"]["findings"]["items"] = {
            "type": "object",
            "properties": runtime_properties,
            "required": list(runtime_properties),
            "additionalProperties": False,
        }
        return schema


_RULE_HEADING = re.compile(r"^##\s+rule:\s*(\S+)\s*$")


def _parse_frontmatter(path: Path) -> tuple[dict[str, object], list[str], int]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"missing or malformed frontmatter in {path}")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"missing or malformed frontmatter in {path}") from error
    loaded: object = yaml.safe_load("\n".join(lines[1:closing_index]))
    if not isinstance(loaded, dict):
        raise ValueError(f"frontmatter must be a mapping in {path}")
    return dict(cast(dict[str, object], loaded)), lines, closing_index


def _derived_rules(body_lines: list[str], path: Path) -> list[str]:
    rules = [match.group(1) for line in body_lines if (match := _RULE_HEADING.match(line))]
    if len(rules) != len(set(rules)):
        raise ValueError(f"duplicate rule id in {path}: duplicate-rule-id")
    if not rules:
        raise ValueError(f"lane has no rule headings in {path}: missing-rule-heading")
    for rule_id in rules:
        heading_index = next(
            i
            for i, line in enumerate(body_lines)
            if (match := _RULE_HEADING.match(line)) and match.group(1) == rule_id
        )
        next_heading = next(
            (
                i
                for i in range(heading_index + 1, len(body_lines))
                if body_lines[i].startswith("## ")
            ),
            len(body_lines),
        )
        if not any(line.strip() for line in body_lines[heading_index + 1 : next_heading]):
            raise ValueError(f"empty rule body in {path}: empty-rule-body:{rule_id}")
    return rules


def load_lane(path: Path, *, allow_legacy: bool = True) -> Lane:
    """Load a Markdown lane document with YAML frontmatter."""

    try:
        metadata, lines, closing_index = _parse_frontmatter(path)
        if "cost" in metadata and "schedule_hint" in metadata:
            raise ValueError("cost and schedule_hint cannot be used together")
        if "cost" in metadata:
            warnings.warn(
                "lane frontmatter cost is deprecated; use schedule_hint instead",
                FutureWarning,
                stacklevel=2,
            )
        body_lines = lines[closing_index + 1 :]
        headings = [line for line in body_lines if _RULE_HEADING.match(line)]
        # Compatibility: old external-registry fixtures have a closed rules list
        # and predate rule headings.  The new format rejects double declaration
        # whenever headings are present.
        if headings:
            if "rules" in metadata:
                raise ValueError("stale rules frontmatter: stale-rules")
            metadata["rules"] = _derived_rules(body_lines, path)
        elif "rules" not in metadata:
            raise ValueError(f"lane has no rule headings in {path}: missing-rule-heading")
        elif not allow_legacy:
            raise ValueError(f"stale rules frontmatter: stale-rules in {path}")
        metadata["prompt_body"] = "\n".join(lines[closing_index + 1 :]).strip()
        lane = Lane.model_validate(metadata)
        if not all(segment and segment not in {".", ".."} for segment in lane.id.split("/")):
            raise ValueError(f"invalid lane id: {lane.id!r}")
        return lane
    except (TypeError, ValidationError, yaml.YAMLError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith(
            ("stale rules", "duplicate rule", "empty rule", "lane has no")
        ):
            raise
        raise ValueError(f"missing or malformed frontmatter in {path}: {error}") from error


def load_new_lane(path: Path) -> Lane:
    """Load only the single-file format (used by packaged/repository linting)."""

    return load_lane(path, allow_legacy=False)
