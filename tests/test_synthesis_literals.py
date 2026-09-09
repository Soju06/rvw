"""Offline regressions for the second Korean synthesis follow-up."""

import json
from pathlib import Path

import pytest
from test_synthesis import FakeRuntime, document, group, merged, outcome_for, target
from test_synthesis_followup import PROSE_FIELDS, english_document, set_prose

from rvw.adjudicate import AdjudicationOutcome
from rvw.merge import MergeResult
from rvw.presentation import PresentationConfig
from rvw.store import RunStore
from rvw.synthesis import synthesize, validate_synthesis


@pytest.mark.parametrize(
    "term",
    ["API", "HTTP URL JSON PII OAuth", "connectedAccountId", '"invented account error"'],
)
def test_unbackticked_prose_is_not_checked_for_invention(term: str) -> None:
    candidate = group()
    value = english_document()
    value.overview = f"The {term} behavior changes how users reconnect their accounts."
    assert validate_synthesis(value, merged(candidate), outcome_for([candidate])) == value


def test_bare_identifiers_remain_protected_for_korean_language_ratio() -> None:
    candidate = group()
    value = document(candidate)
    value.overview = "API HTTP URL JSON PII OAuth HTTPError 오류가 발생하면 요청한 계정의 처리를 중단합니다. 충분히 확인합니다."
    assert validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="ko")


@pytest.mark.parametrize("pr_field", ["pr_title", "pr_body"])
@pytest.mark.parametrize("field", PROSE_FIELDS)
def test_every_prose_field_can_use_pr_text(pr_field: str, field: str) -> None:
    candidate = group()
    pr = target().model_copy(update={pr_field: "Support GmailAccountSync for account updates."})
    value = document(candidate)
    set_prose(value, field, "`GmailAccountSync`가 요청한 계정의 변경 사항을 반영합니다.")
    assert (
        validate_synthesis(
            value, merged(candidate), outcome_for([candidate]), locale="ko", target=pr
        )
        == value
    )


def test_opening_with_no_findings_can_use_pr_text() -> None:
    pr = target().model_copy(update={"pr_title": "Support GmailAccountSync"})
    value = document()
    value.overview = "`GmailAccountSync`가 요청한 계정의 변경 사항을 반영합니다."
    value.first_action = None
    assert validate_synthesis(value, merged(), outcome_for([]), locale="ko", target=pr) == value


@pytest.mark.parametrize(
    "source", ["location", "evidence_location", "evidence_line", "numbered_code"]
)
def test_composed_path_and_established_line_pass(source: str) -> None:
    candidate = group()
    outcome = outcome_for([candidate])
    line = candidate.line if source == "location" else 104
    if source == "evidence_location":
        outcome.evidence[candidate.key] += f"\n{candidate.file}:{line}"
    elif source == "evidence_line":
        outcome.evidence[candidate.key] += f"\nAt line {line}, the mock returns false."
    elif source == "numbered_code":
        outcome.evidence[candidate.key] += f"\n{line}: return false;"
    value = document(candidate)
    value.findings[0].what = f"`{candidate.file}:{line}`에서 조회 인수를 확인하지 않습니다."
    value.overview = value.findings[0].what
    assert validate_synthesis(value, merged(candidate), outcome, locale="ko") == value


@pytest.mark.parametrize("backticks", [True, False])
def test_unestablished_line_is_rejected(backticks: bool) -> None:
    candidate = group()
    outcome = outcome_for([candidate])
    outcome.evidence[candidate.key] += "\nreturn 104;"
    value = document(candidate)
    location = f"{candidate.file}:104"
    if backticks:
        location = f"`{location}`"
    value.findings[0].what = f"{location}에서 조회 인수를 확인하지 않습니다."
    with pytest.raises(ValueError, match="literals absent from source"):
        validate_synthesis(value, merged(candidate), outcome, locale="ko")


@pytest.mark.parametrize(
    "code",
    [
        "vi.mocked( cursors.enableGmailDiscoveryIfUnchangedSince ).mockResolvedValue(false);",
        "vi.mocked(\n cursors.enableGmailDiscoveryIfUnchangedSince\n).mockResolvedValue(false);",
    ],
)
def test_whitespace_normalized_code_passes(code: str) -> None:
    candidate = group()
    outcome = outcome_for([candidate])
    outcome.evidence[candidate.key] += (
        "\n```ts\nvi.mocked(\n    cursors.enableGmailDiscoveryIfUnchangedSince\n"
        ").mockResolvedValue(false);\n```"
    )
    value = document(candidate)
    value.findings[0].what = f"`{code}` 때문에 변경된 계정 정보를 확인할 수 없습니다."
    assert validate_synthesis(value, merged(candidate), outcome, locale="ko") == value


@pytest.mark.parametrize(
    "literal",
    ["LookupRecipient", "lookup_recipient", "src/review/invented.py", "review/lane_lookup.py"],
)
def test_backticked_mutation_or_invented_path_is_rejected(literal: str) -> None:
    candidate = group()
    value = document(candidate)
    value.findings[0].what = f"`{literal}`에서 조회 인수를 확인하지 않습니다."
    with pytest.raises(ValueError, match="literals absent from source"):
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="ko")


def test_normalized_code_cannot_join_separate_sources() -> None:
    candidate = group(body="lookupRecipient(")
    outcome = outcome_for([candidate])
    outcome.evidence[candidate.key] = '"usr_2")'
    value = english_document()
    value.findings[0].what = '`lookupRecipient( "usr_2")` ignores the requested account.'
    with pytest.raises(ValueError, match="literals absent from source"):
        validate_synthesis(value, merged(candidate), outcome)


async def test_runtime_and_retained_synthesis_share_pr_sources(tmp_path: Path) -> None:
    candidate = group()
    pr = target().model_copy(update={"pr_body": "Support GmailAccountSync"})
    value = document(candidate)
    value.overview = "`GmailAccountSync`가 요청한 계정의 변경 사항을 반영합니다."
    runtime = FakeRuntime([value])
    outcome = outcome_for([candidate])
    result, facts = await synthesize(
        target=pr,
        merged=merged(candidate),
        outcome=outcome,
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale="ko"),
        runtime=runtime,
        out_root=tmp_path / "runtime",
    )
    assert result == value
    assert facts.status == "ok"
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["deadline_seconds"] == 300
    run = RunStore(tmp_path / "runs").create(pr)
    run.save_merge(merged(candidate))
    run.save_outcome(outcome)
    run.save_presentation(PresentationConfig(locale="ko"))
    run.save_target(pr)
    run.save_synthesis(value)
    assert run.load_synthesis() == value


async def test_literal_retry_explains_searched_sources_on_one_line(tmp_path: Path) -> None:
    candidate = group()
    invalid = document(candidate)
    invalid.overview = "`inventedAccount`가 요청한 계정의 변경 사항을 반영합니다."
    valid = document(candidate)
    runtime = FakeRuntime([invalid, valid])
    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale="ko"),
        runtime=runtime,
        out_root=tmp_path,
    )
    assert result == valid
    assert facts.status == "ok"
    assert len(runtime.calls) == 2
    feedback = str(runtime.calls[1]["prompt"]).split("# Validation feedback\n")[1]
    lines = [line for line in feedback.splitlines() if "literals absent from source" in line]
    assert len(lines) == 1
    assert "overview" in lines[0] and "inventedAccount" in lines[0]
    assert (
        "not found in finding bodies, adjudication reason, evidence, or pull request text"
        in lines[0]
    )


@pytest.mark.parametrize("attempt", ["initial", "retry"])
def test_persisted_live_1781_korean_outputs_validate(attempt: str) -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "synthesis_live_1781_ko"
    source = json.loads((fixture_dir / "sources.json").read_text(encoding="utf-8"))
    fixture_target = target().model_copy(
        update={"pr_title": source["pr_title"], "pr_body": source["pr_body"], "pr_number": 1781}
    )
    merged_value = MergeResult.model_validate(source["merge"])
    outcome_value = AdjudicationOutcome.model_validate(source["outcome"])
    output = json.loads((fixture_dir / f"{attempt}.json").read_text(encoding="utf-8"))
    assert (
        validate_synthesis(
            output, merged_value, outcome_value, locale="ko", target=fixture_target
        ).model_dump(mode="json")
        == output
    )
