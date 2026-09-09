"""Offline regressions for omission fidelity and synthesis language feedback."""

from pathlib import Path
from typing import Literal

import pytest
from test_synthesis import FakeRuntime, document, group, merged, outcome_for, target

from rvw.presentation import PresentationConfig
from rvw.store import RunStore
from rvw.synthesis import (
    SynthesisDocument,
    build_synthesis_prompt,
    synthesis_protected_literals,
    synthesize,
    validate_synthesis,
)

PROSE_FIELDS = ("overview", "first_action", "title", "what", "consequence", "fix")


def set_prose(value: SynthesisDocument, field: str, prose: str) -> None:
    owner = value if field in ("overview", "first_action") else value.findings[0]
    setattr(owner, field, prose)


def english_document() -> SynthesisDocument:
    value = document(group())
    for field in PROSE_FIELDS:
        set_prose(value, field, "The current implementation loses the previous account identity.")
    return value


def test_unestablished_downstream_literal_can_be_omitted() -> None:
    candidate = group(body="Invalid linkage returns HTTP 503 and reports `hub_request_failed`.")
    outcome = outcome_for([candidate])
    outcome.reasons[candidate.key] = (
        "The local diagnostic omission is established; downstream reporting is not shown."
    )
    outcome.evidence[candidate.key] = (
        'return json({ error: "gmail_account_inventory_unavailable" }, { status: 503 });'
    )
    value = english_document()
    value.findings[
        0
    ].what = "Invalid linkage returns HTTP 503 with `gmail_account_inventory_unavailable`."
    assert "hub_request_failed" not in value.model_dump_json()
    assert validate_synthesis(value, merged(candidate), outcome, locale="en") == value


@pytest.mark.parametrize("field", PROSE_FIELDS)
def test_invented_literal_is_rejected_in_every_prose_field(field: str) -> None:
    candidate = group()
    value = document(candidate)
    set_prose(value, field, "`invented_account_error`가 발생하면 기존 계정이 사라집니다.")
    with pytest.raises(ValueError, match=r"literals absent from source.*invented_account_error"):
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="ko")


@pytest.mark.parametrize(
    "literal",
    [
        "`connectedAccountId`",
        "connectedAccountId",
        "`CONNECTED_ACCOUNT_ID`",
        "`connected_account`",
        '"invented account error"',
        "'invented account error'",
        "`src/review/other.py`",
        "src/review/other.py",
        "xY",
        "HTTPError",
    ],
)
def test_mutated_or_invented_literal_fails_even_if_original_is_repeated(literal: str) -> None:
    candidate = group(body="`connected_account_id` is lost during reauthorization.")
    value = english_document()
    value.findings[0].what = f"`connected_account_id` is replaced with {literal}."
    with pytest.raises(ValueError, match="literals absent from source"):
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="en")


@pytest.mark.parametrize("source", ["body", "reason", "evidence", "path"])
def test_backticks_may_wrap_verbatim_unformatted_source(source: str) -> None:
    candidate = group()
    outcome = outcome_for([candidate])
    literal = candidate.file if source == "path" else 'status = ApiError("account error")'
    if source == "body":
        candidate.bodies.append(literal)
    elif source == "reason":
        outcome.reasons[candidate.key] = literal
    elif source == "evidence":
        outcome.evidence[candidate.key] += "\n" + literal
    value = document(candidate)
    value.findings[0].what = f"`{literal}` 때문에 요청한 계정 정보를 확인할 수 없습니다."
    assert validate_synthesis(value, merged(candidate), outcome, locale="ko") == value
    protected = synthesis_protected_literals(value, merged(candidate), outcome)
    assert literal in protected


@pytest.mark.parametrize(
    ("original", "mutation"),
    [("JSON.stringify", "JSON.parse"), ("lookupRecipient.id", "lookupRecipient.key")],
)
def test_bare_qualified_identifier_cannot_change_its_member(original: str, mutation: str) -> None:
    candidate = group(body=f"{original} ignores the requested user.")
    value = english_document()
    value.findings[0].what = f"{mutation} ignores the requested user."
    with pytest.raises(ValueError, match="literals absent from source"):
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="en")


def test_finding_cannot_borrow_another_findings_literal_but_opening_can() -> None:
    first, second = group("one"), group("two", body="`secondAccount` ignores the user.")
    outcome = outcome_for([first, second])
    value = document(first, second)
    value.overview = "`secondAccount` 때문에 요청한 사용자 정보를 확인할 수 없습니다."
    value.first_action = value.overview
    assert validate_synthesis(value, merged(first, second), outcome, locale="ko") == value
    value.findings[0].what = value.overview
    with pytest.raises(ValueError, match=r"literals absent from source.*secondAccount"):
        validate_synthesis(value, merged(first, second), outcome, locale="ko")


@pytest.mark.parametrize("field", PROSE_FIELDS)
def test_korean_locale_rejects_an_english_field(field: str) -> None:
    candidate = group()
    value = document(candidate)
    set_prose(value, field, "The current implementation loses the previous account identity.")
    label = field if field in ("overview", "first_action") else f"findings[0].{field}"
    with pytest.raises(ValueError) as exc:
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="ko")
    assert str(exc.value) == f"synthesis prose is not in locale 'ko': {label}"


def test_korean_prose_with_backticked_english_identifiers_passes() -> None:
    candidate = group()
    value = document(candidate)
    value.first_action = None
    assert (
        validate_synthesis(value, merged(candidate), outcome_for([candidate]), locale="ko") == value
    )


def test_source_error_string_is_excluded_from_the_language_ratio() -> None:
    candidate = group()
    outcome = outcome_for([candidate])
    literal = "Failed to resolve inventory for the previously connected account"
    outcome.reasons[candidate.key] = f'The local error is "{literal}".'
    value = document(candidate)
    value.findings[0].what = f'조회 실패 시 "{literal}" 오류를 반환합니다.'
    assert validate_synthesis(value, merged(candidate), outcome, locale="ko") == value
    assert literal in synthesis_protected_literals(value, merged(candidate), outcome)


def test_english_locale_rejects_korean_prose() -> None:
    candidate = group()
    with pytest.raises(ValueError, match="synthesis prose is not in locale 'en': overview"):
        validate_synthesis(
            document(candidate), merged(candidate), outcome_for([candidate]), locale="en"
        )


@pytest.mark.parametrize("locale", ["ko", "en"])
def test_prompt_prioritizes_locale_and_backtick_instructions(locale: Literal["ko", "en"]) -> None:
    candidate = group()
    prompt = build_synthesis_prompt(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale=locale),
        budget_seconds=300,
    )
    language = (
        "Write every prose field in Korean, 합니다체."
        if locale == "ko"
        else "Write every prose field in technical-neutral English in the configured register."
    )
    example = (
        "인벤토리 검증이 실패하면 `gmail_account_inventory_unavailable`과 함께 HTTP 503을 반환합니다."
        if locale == "ko"
        else "If inventory validation fails, return HTTP 503 with `gmail_account_inventory_unavailable`."
    )
    assert prompt.splitlines()[2:5] == [
        "# Language",
        f"{language} Identifiers, paths, code and error strings stay in their original form, wrapped in backticks.",
        example,
    ]
    assert (
        "Wrap every identifier, path, code fragment, and error string in backticks in the output."
        in prompt
    )


@pytest.mark.parametrize("correct_retry", [True, False])
async def test_language_retry_names_all_fields_and_keeps_one_retry(
    tmp_path: Path,
    correct_retry: bool,
) -> None:
    candidate = group()
    value = document(candidate)
    runtime = FakeRuntime([english_document(), value if correct_retry else english_document()])
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
    assert len(runtime.calls) == 2
    feedback = str(runtime.calls[1]["prompt"]).split("# Validation feedback\n")[1]
    assert "synthesis prose is not in locale 'ko':" in feedback
    for field in PROSE_FIELDS:
        label = field if field in ("overview", "first_action") else f"findings[0].{field}"
        assert label in feedback
    assert result == (value if correct_retry else None)
    assert facts.status == ("ok" if correct_retry else "fallback:schema-invalid")
    assert all(call["deadline_seconds"] == 300 for call in runtime.calls)


def test_retained_synthesis_checks_the_saved_locale(tmp_path: Path) -> None:
    candidate = group()
    run = RunStore(tmp_path).create(target())
    run.save_merge(merged(candidate))
    run.save_outcome(outcome_for([candidate]))
    run.save_presentation(PresentationConfig(locale="ko"))
    english = english_document()
    english.findings[0].what = (
        "`lookupRecipient` ignores the user and raises `RECIPIENT_NOT_FOUND` "
        "from `src/review/lane_lookup.py`."
    )
    assert validate_synthesis(english, merged(candidate), outcome_for([candidate]), locale="en")
    run.save_synthesis(english)
    assert run.load_synthesis() is None
    run.save_synthesis(document(candidate))
    assert run.load_synthesis() == document(candidate)
