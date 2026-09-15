"""Wire and disk models. See DECISIONS.md ADR-003, ADR-004."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


class Severity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class EffectiveSeverity(StrEnum):
    """Controller severity; never used by the runtime output schema."""

    BLOCKER = "blocker"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    INFO = "info"


class FindingScope(StrEnum):
    CHANGED = "changed"
    UNCHANGED_IN_FILE = "unchanged_in_file"
    OUTSIDE_DIFF = "outside_diff"


def derive_scope_severity(
    severity: Severity, scope: FindingScope
) -> tuple[EffectiveSeverity, Literal["unchanged_in_file", "outside_diff"] | None]:
    """Derive controller severity and demotion provenance from scope."""

    if scope is FindingScope.CHANGED:
        return EffectiveSeverity(severity.value), None
    reason = "unchanged_in_file" if scope is FindingScope.UNCHANGED_IN_FILE else "outside_diff"
    return EffectiveSeverity.INFO, reason


class ScopedFinding(BaseModel):
    """Persist controller decisions separately from the model's severity.

    Legacy artifacts lack diff scope evidence and keep their prior severity.
    Recompute derived fields on load so an inconsistent persisted severity
    cannot promote a finding whose scope is informational.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    severity: Severity
    scope: FindingScope = FindingScope.CHANGED
    effective_severity: EffectiveSeverity = EffectiveSeverity.SUGGESTION
    demotion_reason: Literal["unchanged_in_file", "outside_diff"] | None = None

    @model_validator(mode="after")
    def _derive_scope_severity(self) -> ScopedFinding:
        effective, reason = derive_scope_severity(self.severity, self.scope)
        object.__setattr__(self, "effective_severity", effective)
        object.__setattr__(self, "demotion_reason", reason)
        return self


class Verdict(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


class Tier(StrEnum):
    BASE = "base"
    PROJECT = "project"
    SCOPE = "scope"
    DYNAMIC = "dynamic"


class RuntimeFinding(BaseModel):
    """One finding in the runtime-facing wire contract."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    file: str
    line: int
    severity: Severity
    body: str


class RuntimeLaneOutput(BaseModel):
    """Strict JSON contract a lane runtime must satisfy (ADR-004 D5)."""

    model_config = ConfigDict(extra="forbid")

    verdict: str
    covered: list[str]
    findings: list[RuntimeFinding] = Field(default_factory=list)


class RuntimeAdjudicationItem(BaseModel):
    """One evidence-bearing adjudicator verdict."""

    model_config = ConfigDict(extra="forbid")

    group_key: str
    verdict: Verdict
    reason: str
    evidence: str

    @model_validator(mode="after")
    def _uncertain_requires_reason(self) -> RuntimeAdjudicationItem:
        if self.verdict is Verdict.UNCERTAIN and not self.reason.strip():
            raise ValueError("UNCERTAIN adjudication items require a non-empty reason")
        return self


class RuntimeAdjudication(BaseModel):
    """Strict runtime wire contract for an adjudication batch."""

    model_config = ConfigDict(extra="forbid")

    items: list[RuntimeAdjudicationItem]


class Finding(BaseModel):
    """One defect claim from one lane. Adjudication unit (ADR-003 D1)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    rule_id: str
    file: str
    hunk_id: str
    line: int | None = None
    severity: Severity
    body: str
    anchorable: bool = False
    verdict: Verdict | None = None
    verdict_reason: str | None = None


class LaneOutput(BaseModel):
    """Strict JSON contract a runtime must satisfy (ADR-004 D5)."""

    model_config = ConfigDict(extra="forbid")

    verdict: str
    findings: list[Finding] = Field(default_factory=list)


def finding_schema() -> dict[str, Any]:
    return Finding.model_json_schema()


def lane_output_schema() -> dict[str, Any]:
    return LaneOutput.model_json_schema()
