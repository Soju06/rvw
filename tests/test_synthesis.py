from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

import rvw.synthesis as synthesis_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import LaneCoverage, RunCoverage
from rvw.merge import CollapseGroup, MergeResult
from rvw.presentation import PresentationConfig
from rvw.runtimes import RunResult, RunStatus, RunUsage, RunUsageStatus
from rvw.schema import Severity, Verdict
from rvw.synthesis import (
    SynthesisDocument,
    SynthesisFacts,
    SynthesisFinding,
    build_synthesis_prompt,
    report_synthesis,
    synthesis_protected_literals,
    synthesize,
    validate_synthesis,
)
from rvw.target import ResolvedTarget


def group(
    key: str = "group-1",
    *,
    body: str = (
        "`lookupRecipient` ignores the requested ID and raises "
        '"RECIPIENT_NOT_FOUND" from `src/review/lane_lookup.py`.'
    ),
) -> CollapseGroup:
    return CollapseGroup(
        key=key,
        rule_id="test-ci/critical-flaw",
        file="src/review/lane_lookup.py",
        hunk_id="src/review/lane_lookup.py:67",
        line=67,
        severity=Severity.BLOCKER,
        lane_ids=["test-ci"],
        agreement=2,
        bodies=[body],
        anchorable=True,
        findings=[],
        priority=[0, 2, 0, 3],
    )


def merged(*groups: CollapseGroup) -> MergeResult:
    return MergeResult(groups=list(groups), sites=[], pattern_folds=[], region_folds=[])


def outcome_for(
    groups: Sequence[CollapseGroup],
    *,
    rejected: Sequence[str] = (),
) -> AdjudicationOutcome:
    rejected_set = set(rejected)
    verdicts = {
        candidate.key: (Verdict.REJECTED if candidate.key in rejected_set else Verdict.CONFIRMED)
        for candidate in groups
    }
    return AdjudicationOutcome(
        verdicts=verdicts,
        reasons={candidate.key: "The query arguments are not checked." for candidate in groups},
        evidence={
            candidate.key: (
                "lookupRecipient('usr_2')\n"
                'raise Error("RECIPIENT_NOT_FOUND")\n'
                "src/review/lane_lookup.py"
            )
            for candidate in groups
        },
        replica_votes={candidate.key: [verdicts[candidate.key]] for candidate in groups},
        unresolved=[],
        coerced_rejections=0,
    )


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/review/lane_lookup.py"],
        diff="",
        pr_number=1800,
        pr_title="Keep recipient lookup scoped to the requested user",
        pr_body="Use a repository lookup instead of a shared fixture.",
    )


def document(*groups: CollapseGroup) -> SynthesisDocument:
    return SynthesisDocument(
        overview="이 변경은 수신자 조회를 요청한 사용자에 맞게 고칩니다.",
        first_action="먼저 조회 인수를 검증하는 테스트를 추가해야 합니다.",
        findings=[
            SynthesisFinding(
                key=candidate.key,
                title="다른 사용자의 수신자를 반환할 수 있습니다",
                what=(
                    "`lookupRecipient`가 src/review/lane_lookup.py에서 요청 ID를 무시하고 "
                    '"RECIPIENT_NOT_FOUND"를 반환합니다.'
                ),
                consequence="요청한 사용자와 다른 수신자를 선택할 수 있습니다.",
                fix="조회 인수를 검증하고 해당 ID의 레코드만 반환해야 합니다.",
            )
            for candidate in groups
        ],
    )


class FakeRuntime:
    name = "fake-synthesis"

    def __init__(
        self,
        responses: Sequence[object | None],
        *,
        reasons: Sequence[str] = (),
        walls: Sequence[float] = (),
        usages: Sequence[RunUsage | None] = (),
        error: BaseException | None = None,
    ) -> None:
        self.responses = list(responses)
        self.reasons = list(reasons)
        self.walls = list(walls)
        self.usages = list(usages)
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def execute_raw(
        self,
        *,
        schema: dict[str, Any],
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
        validate: Callable[[object], BaseModel],
    ) -> RunResult[BaseModel]:
        index = len(self.calls)
        self.calls.append(
            {
                "schema": schema,
                "prompt": prompt,
                "run_dir": run_dir,
                "deadline_seconds": deadline_seconds,
                "workdir": workdir,
            }
        )
        if self.error is not None:
            raise self.error
        response = self.responses[index]
        wall = self.walls[index] if index < len(self.walls) else 0.0
        usage = self.usages[index] if index < len(self.usages) else None
        if response is None:
            reason = self.reasons[index] if index < len(self.reasons) else "schema-invalid"
            return RunResult(
                lane_id="synthesis",
                replica=1,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason=reason,
                wall_seconds=wall,
                artifact_dir=run_dir,
                usage=usage,
            )
        try:
            output = validate(response)
        except ValueError:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "out.json").write_text(json.dumps(response), encoding="utf-8")
            return RunResult(
                lane_id="synthesis",
                replica=1,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="schema-invalid",
                wall_seconds=wall,
                artifact_dir=run_dir,
                usage=usage,
            )
        return RunResult(
            lane_id="synthesis",
            replica=1,
            status=RunStatus.VALID,
            output=output,
            invalid_reason=None,
            wall_seconds=wall,
            artifact_dir=run_dir,
            usage=usage,
        )

    async def execute(self, **kwargs: object) -> RunResult:
        raise AssertionError(f"lane execution is forbidden: {kwargs}")


def test_document_and_facts_are_strict() -> None:
    with pytest.raises(ValidationError):
        SynthesisFinding(
            key="key",
            title=" ",
            what="what",
            consequence="consequence",
            fix="fix",
        )
    with pytest.raises(ValidationError):
        SynthesisDocument.model_validate(
            {"overview": "ok", "first_action": None, "findings": [], "extra": True}
        )
    assert SynthesisFacts().model_dump() == {
        "status": "fallback:not-run",
        "model": None,
        "reasoning_effort": None,
        "wall_seconds": None,
        "tool_calls": None,
    }
    for wall in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            SynthesisFacts(wall_seconds=wall)
    for status in ("fallback:", "fallback:bad reason", "fallback:bad\n"):
        with pytest.raises(ValidationError):
            SynthesisFacts(status=status)


def test_schema_is_closed_and_requires_nullable_first_action() -> None:
    schema = synthesis_module.synthesis_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"overview", "first_action", "findings"}
    finding = schema["$defs"]["SynthesisFinding"]
    assert finding["additionalProperties"] is False
    assert set(finding["required"]) == {"key", "title", "what", "consequence", "fix"}
    packaged = json.loads(
        files("rvw").joinpath("resources/schemas/synthesis.schema.json").read_text()
    )
    assert packaged == schema


def test_validate_requires_every_non_rejected_key_exactly_once_and_no_extras() -> None:
    first, second, rejected = group("one"), group("two"), group("rejected")
    combined = merged(first, second, rejected)
    adjudicated = outcome_for([first, second, rejected], rejected=[rejected.key])
    valid = document(first, second)

    assert validate_synthesis(valid.model_dump(), combined, adjudicated) == valid
    duplicate = valid.model_copy(update={"findings": [valid.findings[0], valid.findings[0]]})
    with pytest.raises(ValueError, match="exactly once"):
        validate_synthesis(duplicate, combined, adjudicated)
    extra = valid.model_copy(
        update={"findings": [*valid.findings, document(group("invented")).findings[0]]}
    )
    with pytest.raises(ValueError, match="unexpected"):
        validate_synthesis(extra, combined, adjudicated)


@pytest.mark.parametrize(
    "forbidden",
    [
        "Confirmed:",
        "replica",
        "adjudication",
        "lane",
        "orchestrator",
        "5살",
        "five-year",
        "다섯 살",
    ],
)
def test_validate_rejects_internal_or_audience_vocabulary(forbidden: str) -> None:
    candidate = group()
    invalid = document(candidate)
    invalid.findings[0].consequence = f"{forbidden} internal wording"

    with pytest.raises(ValueError, match="forbidden vocabulary"):
        validate_synthesis(invalid, merged(candidate), outcome_for([candidate]))


@pytest.mark.parametrize("forbidden", ["`Confirmed:`", "replicas", "lanes"])
@pytest.mark.parametrize("field", ["overview", "first_action"])
def test_overview_and_action_cannot_hide_internal_vocabulary(forbidden: str, field: str) -> None:
    candidate = group()
    invalid = document(candidate)
    setattr(invalid, field, f"독자에게 {forbidden} 표현을 노출합니다.")

    with pytest.raises(ValueError, match="forbidden vocabulary"):
        validate_synthesis(invalid, merged(candidate), outcome_for([candidate]))


def test_source_literal_may_contain_forbidden_substring_and_literals_survive() -> None:
    candidate = group()
    synthesized = document(candidate)

    validated = validate_synthesis(synthesized, merged(candidate), outcome_for([candidate]))

    protected = synthesis_protected_literals(validated, merged(candidate), outcome_for([candidate]))
    assert "src/review/lane_lookup.py" in protected
    assert "lookupRecipient" in protected
    assert "RECIPIENT_NOT_FOUND" in protected
    assert all(
        literal in "\n".join(item.what for item in validated.findings)
        for literal in (
            "src/review/lane_lookup.py",
            "lookupRecipient",
            "RECIPIENT_NOT_FOUND",
        )
    )


def test_validate_rejects_changed_code_and_error_literals() -> None:
    candidate = group()
    for source, replacement in (
        ("lookupRecipient", "lookupMember"),
        ("RECIPIENT_NOT_FOUND", "MEMBER_NOT_FOUND"),
    ):
        synthesized = document(candidate)
        synthesized.findings[0].what = synthesized.findings[0].what.replace(source, replacement)
        with pytest.raises(ValueError, match="source literals verbatim"):
            validate_synthesis(synthesized, merged(candidate), outcome_for([candidate]))


def test_metadata_path_need_not_be_duplicated_in_explanation() -> None:
    candidate = group(body="`lookupRecipient` ignores the requested ID.")
    synthesized = document(candidate)
    synthesized.findings[0].what = "`lookupRecipient`가 요청 ID를 무시합니다."

    assert validate_synthesis(synthesized, merged(candidate), outcome_for([candidate]))
    assert candidate.file in synthesis_protected_literals(
        synthesized, merged(candidate), outcome_for([candidate])
    )


def test_prompt_contains_inputs_budget_voice_and_reader_rules() -> None:
    candidate = group()
    coverage = [
        LaneCoverage(
            lane_id="security-exposure",
            dispatched=1,
            valid=0,
            findings=0,
            runs=[
                RunCoverage(
                    replica=1,
                    chunk=1,
                    valid=False,
                    findings=0,
                    invalid_reason="exit_nonzero:124",
                )
            ],
            uncovered=["src/review/lane_lookup.py:60-72"],
        )
    ]
    presentation = PresentationConfig(locale="ko")
    prompt = build_synthesis_prompt(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=coverage,
        status="degraded",
        presentation=presentation,
        budget_seconds=77,
    )

    for text in (
        target().pr_title,
        target().pr_body,
        target().base_sha,
        target().head_sha,
        candidate.key,
        candidate.rule_id,
        candidate.bodies[0],
        "security-exposure",
        "77 seconds",
        "zero tool calls",
        "Purpose before mechanism",
        "one idea per sentence",
        "No condescension",
        "합니다체",
    ):
        assert text is not None and text in prompt


async def test_invalid_content_retries_once_with_validation_diagnostics(
    tmp_path: Path,
) -> None:
    candidate = group()
    invalid = document(candidate).model_dump()
    invalid["findings"] = []
    runtime = FakeRuntime([invalid, document(candidate)], walls=[1.25, 2.75])

    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale="ko"),
        runtime=runtime,
        out_root=tmp_path,
        deadline_seconds=77,
    )

    assert result == document(candidate)
    assert facts.status == "ok"
    assert facts.wall_seconds == 4.0
    assert len(runtime.calls) == 2
    assert "exactly once" in str(runtime.calls[1]["prompt"])
    assert [call["deadline_seconds"] for call in runtime.calls] == [77, 77]
    assert [cast(Path, call["run_dir"]).name for call in runtime.calls] == ["r1", "r1"]
    assert [cast(Path, call["run_dir"]).parent.name for call in runtime.calls] == [
        "initial",
        "retry",
    ]


async def test_schema_retry_includes_field_validation_error(tmp_path: Path) -> None:
    candidate = group()
    invalid = document(candidate).model_dump()
    del invalid["first_action"]
    runtime = FakeRuntime([invalid, document(candidate)])

    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(),
        runtime=runtime,
        out_root=tmp_path,
    )

    assert result == document(candidate)
    assert facts.status == "ok"
    assert "first_action" in str(runtime.calls[1]["prompt"])
    assert "Field required" in str(runtime.calls[1]["prompt"])


async def test_second_invalid_output_falls_back_with_aggregated_telemetry(
    tmp_path: Path,
) -> None:
    candidate = group()
    usage = RunUsage(
        model="gpt-6-astra",
        reasoning_effort="high",
        status=RunUsageStatus.INVALID,
        wall_seconds=1.5,
        tool_calls=0,
    )
    runtime = FakeRuntime([None, None], walls=[1.5, 2.5], usages=[usage, usage])

    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="failed",
        presentation=PresentationConfig(),
        runtime=runtime,
        out_root=tmp_path,
        deadline_seconds=500,
    )

    assert result is None
    assert facts == SynthesisFacts(
        status="fallback:schema-invalid",
        model="gpt-6-astra",
        reasoning_effort="high",
        wall_seconds=4.0,
        tool_calls=0,
    )
    assert len(runtime.calls) == 2
    assert all(call["deadline_seconds"] == 120 for call in runtime.calls)


async def test_process_failure_and_exception_fall_back_without_retry(tmp_path: Path) -> None:
    candidate = group()
    process_runtime = FakeRuntime([None], reasons=["exit_nonzero:124"], walls=[3.0])
    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(),
        runtime=process_runtime,
        out_root=tmp_path / "process",
    )
    assert result is None
    assert facts.status == "fallback:exit_nonzero:124"
    assert len(process_runtime.calls) == 1

    exception_runtime = FakeRuntime([], error=RuntimeError("boom"))
    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(),
        runtime=exception_runtime,
        out_root=tmp_path / "exception",
    )
    assert result is None
    assert facts.status == "fallback:runtime-error"
    assert len(exception_runtime.calls) == 1
    diagnostic = tmp_path / "exception" / "initial" / "r1" / "runtime-error.json"
    assert diagnostic.is_file()
    assert "RuntimeError" in diagnostic.read_text(encoding="utf-8")


async def test_partial_telemetry_becomes_unknown_when_retry_raises(tmp_path: Path) -> None:
    candidate = group()
    invalid = document(candidate).model_dump()
    invalid["findings"] = []
    usage = RunUsage(
        model="gpt-6-astra",
        reasoning_effort="high",
        status=RunUsageStatus.COMPLETED,
        wall_seconds=1.0,
        tool_calls=0,
    )
    # The first schema-valid response fails fidelity. The absent scripted retry raises.
    runtime = FakeRuntime([invalid], walls=[1.0], usages=[usage])

    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(),
        runtime=runtime,
        out_root=tmp_path,
    )

    assert result is None
    assert facts.status == "fallback:runtime-error"
    assert facts.wall_seconds is None
    assert facts.tool_calls is None


async def test_cancellation_is_not_converted_to_fallback(tmp_path: Path) -> None:
    candidate = group()
    runtime = FakeRuntime([], error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await synthesize(
            target=target(),
            merged=merged(candidate),
            outcome=outcome_for([candidate]),
            coverage=[],
            status="complete",
            presentation=PresentationConfig(),
            runtime=runtime,
            out_root=tmp_path,
        )


def test_report_synthesis_contains_only_opening_prose() -> None:
    candidate = group()
    assert report_synthesis(document(candidate)) == (
        "이 변경은 수신자 조회를 요청한 사용자에 맞게 고칩니다.\n\n"
        "먼저 조회 인수를 검증하는 테스트를 추가해야 합니다."
    )
    assert report_synthesis(document(candidate).model_copy(update={"first_action": None})) == (
        "이 변경은 수신자 조회를 요청한 사용자에 맞게 고칩니다."
    )
