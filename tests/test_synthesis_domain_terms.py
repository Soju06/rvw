"""Domain vocabulary and explicit escapes do not hide synthesis process prose."""

from __future__ import annotations

import pytest
from test_synthesis import document, group, merged, outcome_for, target

from rvw.presentation import PresentationConfig, VoiceConfig
from rvw.schema import Verdict
from rvw.synthesis import build_synthesis_prompt, validate_synthesis


def test_bori_discovery_path_is_domain_evidence_without_prose_occurrence() -> None:
    path = "apps/api/src/services/life-gmail-discovery-reconciliation.ts"
    finding = group().model_copy(update={"file": path})
    value = document(finding)
    value.findings[0].consequence = "discovery 재조정이 실패하면 계정 동기화가 중단됩니다."
    validate_synthesis(value, merged(finding), outcome_for([finding]), locale="ko")


def test_allowed_terms_exempts_actual_process_phrase_without_domain_source() -> None:
    finding = group()
    value = document(finding)
    value.findings[
        0
    ].consequence = "the controller 요청이 실패하면 사용자의 계정 동기화가 중단되어 새 메일을 확인할 수 없습니다."
    with pytest.raises(ValueError, match="forbidden vocabulary"):
        validate_synthesis(value, merged(finding), outcome_for([finding]), locale="ko")
    validate_synthesis(
        value,
        merged(finding),
        outcome_for([finding]),
        locale="ko",
        presentation=PresentationConfig(
            locale="ko", voice=VoiceConfig(allowed_terms=["controller"])
        ),
    )


def test_prompt_supplies_repository_allowed_terms_to_the_writer() -> None:
    finding = group()
    prompt = build_synthesis_prompt(
        target=target(),
        merged=merged(finding),
        outcome=outcome_for([finding]),
        coverage=[],
        status="complete",
        budget_seconds=60,
        presentation=PresentationConfig(
            voice=VoiceConfig(allowed_terms=["orchestrator", "custom_domain_term"])
        ),
    )
    assert 'allowed_terms: ["orchestrator", "custom_domain_term"]' in prompt


@pytest.mark.parametrize("source", ["rejected_finding", "changed_path"])
def test_domain_vocabulary_uses_all_review_sources(source: str) -> None:
    finding = group()
    groups = [finding]
    review_target = target()
    if source == "rejected_finding":
        groups.append(
            finding.model_copy(update={"key": "rejected", "bodies": ["The controller retries."]})
        )
    else:
        review_target = review_target.model_copy(update={"changed_paths": ["src/controller.py"]})
    outcome = outcome_for(groups)
    if source == "rejected_finding":
        outcome.verdicts["rejected"] = Verdict.REJECTED
    value = document(finding)
    value.findings[
        0
    ].consequence = "the controller 요청이 실패하면 사용자의 계정 동기화가 중단되어 새 메일을 확인할 수 없습니다."

    validate_synthesis(value, merged(*groups), outcome, locale="ko", target=review_target)
