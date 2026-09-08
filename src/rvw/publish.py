"""Publish file-first reports as GitHub comment reviews.

Inline-anchor fallback is deliberately bulk and bounded: publication first attempts
one review containing every inline anchor. If GitHub rejects that review with HTTP
422, all inline comments move under ``the inline-anchor fallback section`` in the review body and
the whole review is retried once. GitHub rejects the complete review when any one
anchor is invalid, while per-comment probing would cost N API calls; this strategy
is deterministic and capped at two calls.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from rvw.adjudicate import AdjudicationOutcome
from rvw.i18n import Locale, t
from rvw.langgate import Rewriter, RuntimeRewriter, enforce_language_sync
from rvw.merge import CollapseGroup, MergeResult
from rvw.presentation import PresentationConfig
from rvw.publication import failed_lane_ids, render_publication, render_publication_item
from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode
from rvw.schema import Verdict
from rvw.store import RunHandle, StageMissing

if TYPE_CHECKING:
    from rvw.gate import GateVerdict

_HTTP_STATUS = re.compile(r"(?:HTTP\s+|status(?: code)?[=: ]+)(?P<status>[1-5][0-9]{2})", re.I)
_COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")


class PublishResult(BaseModel):
    """Observable result of a dry-run or GitHub COMMENT review."""

    model_config = ConfigDict(extra="forbid")

    review_url: str | None
    inline_count: int
    body_fallback_count: int
    state: Literal["commented"]
    language_fallback_used: bool = False


class PublishError(RuntimeError):
    """GitHub review creation failed."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


class PublicationLanguageMismatch(PublishError):
    reason = "publication_language_mismatch"

    def __init__(self, locale: Locale) -> None:
        super().__init__(t("publish.language_mismatch", locale))


def _check_publication(
    documents: list[str],
    *,
    run_dir: Path,
    locale: Locale,
    rewriter: Rewriter | None,
    allow_language_fallback: bool,
    protected_literals: Sequence[str] = (),
) -> tuple[tuple[str, ...], bool]:
    from rvw.store import _write_json
    from rvw.summary import ExecutionSummary

    checked = enforce_language_sync(
        documents,
        locale=locale,
        rewriter=rewriter
        if rewriter is not None
        else RuntimeRewriter(
            CodexRuntime(mode=CodexRuntimeMode.TOOL_LESS),
            run_dir,
        ),
        allow_language_fallback=allow_language_fallback,
        protected_literals=protected_literals,
    )
    facts = {
        "publication_failure": checked.failure_reason,
        "language_fallback_used": checked.language_fallback_used,
        "rewrite_attempted": checked.rewrite_attempted,
    }
    _write_json(run_dir / "publication.json", facts)
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        summary = ExecutionSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    else:
        presentation = RunHandle(run_dir.name, run_dir).load_presentation()
        summary = ExecutionSummary(presentation=presentation, markdown=t("pub.incomplete", locale))
    summary.publication_failure = checked.failure_reason
    summary.language_fallback_used = checked.language_fallback_used
    _write_json(summary_path, summary.model_dump(mode="json"))
    if not checked.publishable:
        (run_dir / "publish-payload.json").unlink(missing_ok=True)
        raise PublicationLanguageMismatch(locale)
    return checked.documents, checked.language_fallback_used


def _run(cmd: list[str], input_json: str) -> str:
    """Execute one ``gh`` request; kept as the publication test seam."""

    try:
        completed = subprocess.run(
            cmd,
            input=input_json,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or str(exc)
        match = _HTTP_STATUS.search(detail)
        status = int(match.group("status")) if match is not None else None
        raise PublishError(detail.strip(), status_code=status) from exc
    except OSError as exc:
        raise PublishError(str(exc)) from exc
    return completed.stdout


def _confirmed_inline_groups(
    merged: MergeResult, outcome: AdjudicationOutcome | None
) -> list[CollapseGroup]:
    if outcome is None:
        return []
    return [
        group
        for group in merged.groups
        if outcome.verdicts.get(group.key) is Verdict.CONFIRMED
        and group.anchorable
        and group.line is not None
    ]


def _payload(*, body: str, comments: list[dict[str, object]] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"event": "COMMENT", "body": body}
    if comments:
        payload["comments"] = comments
    return payload


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _review_url(raw: str, *, locale: Locale = "en") -> str:
    try:
        value = json.loads(raw)["html_url"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublishError(t("publish.missing_url", locale)) from exc
    if not isinstance(value, str):
        raise PublishError(t("publish.invalid_url", locale))
    return value


def _fallback_body(body: str, comments: list[dict[str, object]], locale: Locale) -> str:
    items = [
        f"#### `{comment['path']}:{comment['line']}`\n\n{comment['body']}" for comment in comments
    ]
    return (
        body.rstrip()
        + "\n\n"
        + t("publish.fallback_heading", locale)
        + "\n\n"
        + "\n\n".join(items)
        + "\n"
    )


def publish_review(
    *,
    run: RunHandle,
    repo: str,
    pr_number: int,
    report_md: str,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    execute: bool,
    locale: Locale | None = None,
    presentation: PresentationConfig | None = None,
    gate_verdict: GateVerdict | None = None,
    rewriter: Rewriter | None = None,
    allow_language_fallback: bool = False,
) -> PublishResult:
    """Build or execute one GitHub COMMENT review from persisted run artifacts."""

    del report_md
    presentation = presentation or run.load_presentation()
    if locale is not None:
        presentation = presentation.model_copy(update={"locale": locale})
    locale = presentation.locale
    inline_groups = _confirmed_inline_groups(merged, outcome)
    try:
        coverage = run.load_discover().coverage
    except StageMissing:
        coverage = []
    try:
        summary = run.load_summary()
    except StageMissing:
        summary = None
    body = render_publication(
        merged=merged,
        outcome=outcome,
        coverage=coverage,
        presentation=presentation,
        excluded_keys=frozenset(group.key for group in inline_groups),
        summary=summary,
    )
    if gate_verdict is not None:
        from rvw.special_publication import render_gate_publication

        body = render_gate_publication(gate_verdict, merged, outcome, presentation)
    comments: list[dict[str, object]] = [
        {
            "path": group.file,
            "line": group.line,
            "side": "RIGHT",
            "body": render_publication_item(group, outcome, presentation=presentation, inline=True),
        }
        for group in inline_groups
    ]
    fallback_body = _fallback_body(body, comments, locale)
    documents, fallback_used = _check_publication(
        [body, *(str(comment["body"]) for comment in comments), fallback_body],
        run_dir=run.dir,
        locale=locale,
        rewriter=rewriter,
        allow_language_fallback=allow_language_fallback,
        # Lane identifiers named by the failed-lanes sentence are data, not prose.
        protected_literals=failed_lane_ids(coverage),
    )
    body, fallback_body = documents[0], documents[-1]
    for comment, rewritten in zip(comments, documents[1:-1], strict=True):
        comment["body"] = rewritten
    payload = _payload(body=body, comments=comments)
    payload_text = _json_text(payload)

    if not execute:
        (run.dir / "publish-payload.json").write_text(f"{payload_text}\n", encoding="utf-8")
        return PublishResult(
            review_url=None,
            inline_count=len(inline_groups),
            body_fallback_count=0,
            state="commented",
            language_fallback_used=fallback_used,
        )

    command = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repo}/pulls/{pr_number}/reviews",
        "--input",
        "-",
    ]
    try:
        raw = _run(command, payload_text)
    except PublishError as exc:
        if exc.status_code != 422 or not inline_groups or outcome is None:
            raise
        fallback = _payload(body=fallback_body)
        raw = _run(command, _json_text(fallback))
        return PublishResult(
            review_url=_review_url(raw, locale=locale),
            inline_count=0,
            body_fallback_count=len(inline_groups),
            state="commented",
            language_fallback_used=fallback_used,
        )

    return PublishResult(
        review_url=_review_url(raw, locale=locale),
        inline_count=len(inline_groups),
        body_fallback_count=0,
        state="commented",
        language_fallback_used=fallback_used,
    )


def publish_body_review(
    *,
    run_dir: Path,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    execute: bool,
    locale: Locale = "en",
    rewriter: Rewriter | None = None,
    allow_language_fallback: bool = False,
) -> PublishResult:
    """Persist and optionally send one body-only GitHub COMMENT review."""

    if _COMMIT_ID.fullmatch(commit_id) is None:
        raise ValueError(t("publish.invalid_commit", locale))
    documents, fallback_used = _check_publication(
        [body],
        run_dir=run_dir,
        locale=locale,
        rewriter=rewriter,
        allow_language_fallback=allow_language_fallback,
    )
    payload = _payload(body=documents[0])
    payload["commit_id"] = commit_id
    payload_text = _json_text(payload)
    (run_dir / "publish-payload.json").write_text(
        f"{payload_text}\n",
        encoding="utf-8",
    )
    if not execute:
        return PublishResult(
            review_url=None,
            inline_count=0,
            body_fallback_count=0,
            state="commented",
            language_fallback_used=fallback_used,
        )

    command = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repo}/pulls/{pr_number}/reviews",
        "--input",
        "-",
    ]
    raw = _run(command, payload_text)
    return PublishResult(
        review_url=_review_url(raw, locale=locale),
        inline_count=0,
        body_fallback_count=0,
        state="commented",
        language_fallback_used=fallback_used,
    )


__all__ = [
    "PublishError",
    "PublishResult",
    "publish_body_review",
    "publish_review",
]
