"""Lane document loading and runtime output-schema generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier

_SEVERITY_ORDER = (Severity.SUGGESTION, Severity.WARNING, Severity.BLOCKER)


class Lane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(alias="lane")
    tier: Tier
    cost: Literal["light", "normal", "heavy"] = "normal"
    rules: list[str] = Field(min_length=1)
    severity_cap: Severity = Severity.BLOCKER
    covered_by_others: Literal["inject"] | None = None
    # Lane lifecycle: "pending" = not yet gated by `rvw sample --compare-free`
    # (ADR-004 verification). None = validated / pre-dates the gate.
    validation: Literal["pending"] | None = None
    scope: Literal["diff", "direct-deps", "repository"] = "repository"
    requires_brief: bool = False
    prompt_body: str

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


def load_lane(path: Path) -> Lane:
    """Load a Markdown lane document with YAML frontmatter."""

    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"missing or malformed frontmatter in {path}")

    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"missing or malformed frontmatter in {path}") from error

    try:
        loaded: object = yaml.safe_load("\n".join(lines[1:closing_index]))
        if not isinstance(loaded, dict):
            raise TypeError("frontmatter must be a mapping")
        metadata = dict(cast(dict[str, object], loaded))
        metadata["prompt_body"] = "\n".join(lines[closing_index + 1 :]).strip()
        return Lane.model_validate(metadata)
    except (TypeError, ValidationError, yaml.YAMLError) as error:
        raise ValueError(f"missing or malformed frontmatter in {path}: {error}") from error
