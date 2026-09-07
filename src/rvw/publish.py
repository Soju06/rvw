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
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from rvw.adjudicate import AdjudicationOutcome
from rvw.i18n import Locale, t
from rvw.merge import CollapseGroup, MergeResult
from rvw.presentation import PresentationConfig
from rvw.publication import render_publication, render_publication_item
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


class PublishError(RuntimeError):
    """GitHub review creation failed."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


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
    payload = _payload(body=body, comments=comments)
    payload_text = _json_text(payload)

    if not execute:
        (run.dir / "publish-payload.json").write_text(f"{payload_text}\n", encoding="utf-8")
        return PublishResult(
            review_url=None,
            inline_count=len(inline_groups),
            body_fallback_count=0,
            state="commented",
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
        fallback = _payload(body=_fallback_body(body, comments, locale))
        raw = _run(command, _json_text(fallback))
        return PublishResult(
            review_url=_review_url(raw, locale=locale),
            inline_count=0,
            body_fallback_count=len(inline_groups),
            state="commented",
        )

    return PublishResult(
        review_url=_review_url(raw, locale=locale),
        inline_count=len(inline_groups),
        body_fallback_count=0,
        state="commented",
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
) -> PublishResult:
    """Persist and optionally send one body-only GitHub COMMENT review."""

    if _COMMIT_ID.fullmatch(commit_id) is None:
        raise ValueError(t("publish.invalid_commit", locale))
    payload = _payload(body=body)
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
    )


__all__ = [
    "PublishError",
    "PublishResult",
    "publish_body_review",
    "publish_review",
]
