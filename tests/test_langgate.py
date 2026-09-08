"""Publication language checks protect facts while allowing one prose rewrite."""

from pathlib import Path
from typing import cast

import pytest

from rvw.i18n import t
from rvw.langgate import (
    RuntimeRewriter,
    check_language,
    enforce_language,
    enforce_language_sync,
)
from rvw.runtimes import RunResult, RunStatus
from rvw.runtimes import Runtime as RuntimeProtocol

KO = "검토되지 않은 변경 구간이 있습니다. 잘못된 입력을 먼저 확인하고 수정해야 합니다."
EN = "The unchecked input causes a failure. Validate the input before using it."


class FakeRewriter:
    def __init__(self, replacement: str = KO, *, corrupt: bool = False) -> None:
        self.replacement = replacement
        self.corrupt = corrupt
        self.calls: list[tuple[str, ...]] = []

    async def rewrite(self, segments: tuple[str, ...], *, locale: str) -> list[str]:
        self.calls.append(segments)
        return [self.replacement] * (len(segments) + self.corrupt)


@pytest.mark.parametrize(
    ("text", "locale", "expected"),
    [
        (KO, "ko", True),
        (KO, "en", False),
        (EN, "en", True),
        (EN, "ko", False),
        ("가" * 12 + "a" * 8, "ko", True),
        ("가" * 11 + "a" * 9, "ko", False),
        ("a" * 18 + "ж" * 2, "en", True),
        ("a" * 17 + "ж" * 3, "en", False),
        ("a" * 19 + "가", "en", False),
        ("ж" * 12, "en", False),
        ("a" * 11, "ko", True),
        ("a" * 12, "ko", False),
    ],
)
def test_language_thresholds(text: str, locale: str, expected: bool) -> None:
    assert check_language(text, locale) is expected


@pytest.mark.parametrize("fence", ["```", "~~~~"])
def test_language_ignores_source_and_technical_tokens(fence: str) -> None:
    markdown = (
        f"{KO}\n\n{fence}python\n{EN}\n{fence}\n"
        f"`{EN}` src/long_english_file.py:123 aVeryLongSymbolName "
        "https://example.test/long/english/text 12345\n"
    )
    assert check_language(markdown, "ko")
    assert not check_language(markdown, "en")


async def test_matching_language_never_calls_rewriter() -> None:
    fake = FakeRewriter()
    result = await enforce_language([KO], locale="ko", rewriter=fake)
    assert result.publishable
    assert result.documents == (KO,)
    assert not result.rewrite_attempted
    assert fake.calls == []


async def test_single_rewrite_sees_only_prose_preserves_facts_and_fences() -> None:
    fence = "```python\nassert englishEvidence == 3\n```"
    source = f"**Blocker · `bori/schema-sot-bypass`**\n\n`src/main.py:42`\n\n{EN}\n\n{fence}"
    fake = FakeRewriter()
    result = await enforce_language([source], locale="ko", rewriter=fake)
    assert result.publishable
    assert result.rewrite_attempted
    assert len(fake.calls) == 1
    supplied = "".join(fake.calls[0])
    for immutable in ["bori/schema-sot-bypass", "src/main.py:42", "Blocker", fence]:
        assert immutable not in supplied
        assert immutable in result.documents[0]
    assert check_language(result.documents[0], "ko")


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize(
    "replacement", [EN, "```\ninjected\n```", "src/changed.py:7", "CONFIRMED", "Warning"]
)
async def test_failed_or_mutating_rewrite_never_publishes_rewritten_text(
    fallback: bool, replacement: str
) -> None:
    fake = FakeRewriter(replacement)
    result = await enforce_language(
        [EN], locale="ko", rewriter=fake, allow_language_fallback=fallback
    )
    assert len(fake.calls) == 1
    assert result.publishable is fallback
    assert result.language_fallback_used is fallback
    assert result.documents == ((EN,) if fallback else ())
    assert result.failure_reason == (None if fallback else "publication_language_mismatch")


async def test_rewrite_segment_count_is_strict_and_all_documents_share_one_pass() -> None:
    fake = FakeRewriter(corrupt=True)
    result = await enforce_language([EN, EN], locale="ko", rewriter=fake)
    assert not result.publishable
    assert result.documents == ()
    assert len(fake.calls) == 1


async def test_rewriter_failure_fails_closed() -> None:
    class Broken:
        async def rewrite(self, segments: tuple[str, ...], *, locale: str) -> list[str]:
            raise RuntimeError("runtime unavailable")

    result = await enforce_language([EN], locale="ko", rewriter=Broken())
    assert not result.publishable
    assert result.failure_reason == "publication_language_mismatch"


def test_unclosed_and_nested_fences_never_leak_evidence_to_rewriter() -> None:
    assert check_language(f"{KO}\n~~~~\n```\n{EN}\n```\n~~~~\n", "ko")
    assert check_language(f"{KO}\n```python\n{EN}", "ko")


def test_language_excludes_non_http_urls() -> None:
    assert check_language("mailto:longenglishaddress@example.test", "ko")
    assert check_language("ssh://longenglishusername@example.test/repository", "ko")


async def test_configured_severity_and_verdict_labels_are_immutable() -> None:
    source = f"**수정 필요 · `bori/rule`**\n\n{EN}"
    fake = FakeRewriter()
    result = await enforce_language(
        [source], locale="ko", rewriter=fake, protected_literals=("수정 필요",)
    )
    assert result.publishable
    assert "수정 필요" not in "".join(fake.calls[0])
    assert result.documents[0].count("**수정 필요 · `bori/rule`**") == 1


@pytest.mark.parametrize("severity", ["blocker", "warning", "suggestion"])
async def test_locale_severity_is_protected_without_caller_supplied_literals(severity: str) -> None:
    label = t("severity." + severity, "ko")
    source = f"**{label} · `bori/rule`**\n\n{EN}"
    fake = FakeRewriter()
    result = await enforce_language([source], locale="ko", rewriter=fake)
    assert result.publishable
    assert label not in fake.calls[0]
    assert f"**{label} · `bori/rule`**" in result.documents[0]


async def test_sync_gate_can_be_used_from_existing_async_pipeline() -> None:
    result = enforce_language_sync([EN], locale="ko", rewriter=FakeRewriter())
    assert result.publishable


async def test_runtime_rewriter_uses_one_bounded_raw_execution(tmp_path: Path) -> None:
    calls = []

    class Runtime:
        async def execute_raw(self, **kwargs):
            calls.append(kwargs)
            value = kwargs["validate"]({"segments": [KO]})
            return RunResult(
                lane_id="rewrite",
                replica=1,
                status=RunStatus.VALID,
                output=value,
                invalid_reason=None,
                wall_seconds=0,
                artifact_dir=tmp_path,
            )

    rewriter = RuntimeRewriter(cast(RuntimeProtocol, Runtime()), tmp_path, deadline_seconds=5)
    assert tuple(await rewriter.rewrite((EN,), locale="ko")) == (KO,)
    assert len(calls) == 1
    call = calls[0]
    assert call["deadline_seconds"] == 5
    assert call["run_dir"] == tmp_path / "language-rewrite" / "r1"
    assert call["schema"]["additionalProperties"] is False
    assert call["schema"]["properties"]["segments"]["minItems"] == 1
    assert call["schema"]["properties"]["segments"]["maxItems"] == 1
    with pytest.raises(ValueError):
        call["validate"]({"segments": [KO, KO]})


def test_protected_lane_identifiers_are_not_scored_as_prose() -> None:
    lanes = ["correctness", "hygiene", "contracts", "security-exposure", "ci-integrity"]
    sentence = f"검토를 완료하지 못한 규칙 묶음 {len(lanes)}개: {', '.join(lanes)}."
    # Unprotected, five Latin lane ids outweigh the Korean chrome on this line.
    assert not check_language(sentence, "ko")
    assert check_language(sentence, "ko", protected_literals=lanes)
    # Protection never hides genuinely foreign prose elsewhere on the line.
    assert not check_language(
        sentence + " This explanation is written in English prose.", "ko", protected_literals=lanes
    )
    assert check_language(f"Rule sets that did not finish: 2 ({lanes[0]}, {lanes[1]}).", "en")
