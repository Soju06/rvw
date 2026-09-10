"""Strict, immutable repository presentation settings and parsing."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKTREE_RULE_WARNING = (
    "WARNING: .rvw rules loaded from the working tree via "
    "--allow-worktree-rules; this run is non-SoT."
)


class PresentationConfigInvalid(ValueError):
    """Presentation configuration cannot be trusted or parsed."""

    reason = "presentation_config_invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.reason}: {detail}")


class VoiceConfig(BaseModel):
    """Repository-selected reviewer voice used only for presentation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, serialize_by_alias=True)

    audience: Literal["engineers", "mixed"] = "engineers"
    register_: Literal["formal", "neutral"] = Field(default="formal", alias="register")
    guidance: str | None = Field(default=None, max_length=800)
    examples: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=3
    )
    allowed_terms: list[str] = Field(default_factory=list)

    @field_validator("guidance")
    @classmethod
    def _plain_multiline_guidance(cls, value: str | None) -> str | None:
        if value is not None and any(
            char != "\n" and unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for char in value
        ):
            raise ValueError("voice guidance must contain plain text")
        return value

    @field_validator("examples")
    @classmethod
    def _bounded_examples(cls, value: list[str]) -> list[str]:
        for example in value:
            if any(
                char != "\n" and unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                for char in example
            ):
                raise ValueError("voice examples must contain plain text")
            if len(example) > 200:
                raise ValueError("voice examples must be at most 200 characters")
        return value

    @field_validator("allowed_terms")
    @classmethod
    def _plain_allowed_terms(cls, value: list[str]) -> list[str]:
        for term in value:
            if any(
                char != "\n" and unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                for char in term
            ):
                raise ValueError("voice allowed terms must contain plain text")
        return value


class SynthesisConfig(BaseModel):
    """Repository-selected synthesis execution setting."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    enabled: bool = True


class PresentationConfig(BaseModel):
    """Base-ref presentation snapshot, safe to retain in strict run contracts."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    display_name: str = Field(default="rvw", min_length=1, max_length=80)
    short_name: str = Field(default="rvw", min_length=1, max_length=40)
    locale: Literal["ko", "en"] = "en"
    footer: str | None = Field(default=None, max_length=240)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)

    @field_validator("display_name", "short_name")
    @classmethod
    def _nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("presentation name must not be blank")
        return value

    @field_validator("display_name", "short_name", "footer")
    @classmethod
    def _plain_single_line(cls, value: str | None) -> str | None:
        if value is not None and any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value
        ):
            raise ValueError(
                "presentation text must be single-line and contain no control characters"
            )
        return value


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than permitting ambiguous configuration."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise PresentationConfigInvalid("configuration keys must be strings") from exc
            if duplicate:
                raise PresentationConfigInvalid("duplicate configuration key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_presentation_config(raw: str) -> PresentationConfig:
    try:
        return PresentationConfig.model_validate(yaml.load(raw, Loader=_UniqueKeyLoader))
    except (ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, PresentationConfigInvalid):
            raise
        raise PresentationConfigInvalid(str(exc)) from exc
