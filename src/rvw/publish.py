"""Publish file-first reports as GitHub comment reviews.

Inline-anchor fallback is deliberately bulk and bounded: publication first attempts
one review containing every inline anchor. If GitHub rejects that review with HTTP
422, all inline comments move under ``### 앵커 실패 항목`` in the review body and
the whole review is retried once. GitHub rejects the complete review when any one
anchor is invalid, while per-comment probing would cost N API calls; this strategy
is deterministic and capped at two calls.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from rvw.adjudicate import AdjudicationOutcome
from rvw.merge import CollapseGroup, MergeResult
from rvw.report import render_group_item
from rvw.schema import Verdict
from rvw.store import RunHandle

_HTTP_STATUS = re.compile(r"(?:HTTP\s+|status(?: code)?[=: ]+)(?P<status>[1-5][0-9]{2})", re.I)
_CONFIRMED_HEADING = "## 확정 발견 (CONFIRMED)"


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


def _body_without_inline(
    report_md: str,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    inline_keys: set[str],
) -> str:
    if not inline_keys or outcome is None or _CONFIRMED_HEADING not in report_md:
        return report_md

    start = report_md.index(_CONFIRMED_HEADING)
    next_section = report_md.find("\n## ", start + len(_CONFIRMED_HEADING))
    if next_section < 0:
        next_section = len(report_md)
    before = report_md[:start].rstrip()
    after = report_md[next_section:].lstrip()
    retained = [
        group
        for group in merged.groups
        if outcome.verdicts.get(group.key) is Verdict.CONFIRMED and group.key not in inline_keys
    ]
    sections = [before]
    if retained:
        sections.append(
            f"{_CONFIRMED_HEADING}\n\n"
            + "\n\n".join(render_group_item(group, outcome) for group in retained)
        )
    if after:
        sections.append(after)
    return "\n\n".join(section for section in sections if section) + "\n"


def _payload(
    *,
    body: str,
    inline_groups: list[CollapseGroup],
    outcome: AdjudicationOutcome | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"event": "COMMENT", "body": body}
    if inline_groups:
        payload["comments"] = [
            {
                "path": group.file,
                "line": group.line,
                "side": "RIGHT",
                "body": render_group_item(group, outcome),
            }
            for group in inline_groups
        ]
    return payload


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _review_url(raw: str) -> str:
    try:
        value = json.loads(raw)["html_url"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublishError("GitHub response did not contain html_url") from exc
    if not isinstance(value, str):
        raise PublishError("GitHub response html_url was not a string")
    return value


def _fallback_body(body: str, groups: list[CollapseGroup], outcome: AdjudicationOutcome) -> str:
    items = []
    for group in groups:
        line = group.line if group.line is not None else "unknown"
        items.append(f"#### `{group.file}:{line}`\n\n{render_group_item(group, outcome)}")
    return body.rstrip() + "\n\n### 앵커 실패 항목\n\n" + "\n\n".join(items) + "\n"


def publish_review(
    *,
    run: RunHandle,
    repo: str,
    pr_number: int,
    report_md: str,
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    execute: bool,
) -> PublishResult:
    """Build or execute one GitHub COMMENT review from persisted run artifacts."""

    inline_groups = _confirmed_inline_groups(merged, outcome)
    inline_keys = {group.key for group in inline_groups}
    body = _body_without_inline(report_md, merged, outcome, inline_keys)
    payload = _payload(body=body, inline_groups=inline_groups, outcome=outcome)
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
        fallback = _payload(
            body=_fallback_body(body, inline_groups, outcome),
            inline_groups=[],
            outcome=outcome,
        )
        raw = _run(command, _json_text(fallback))
        return PublishResult(
            review_url=_review_url(raw),
            inline_count=0,
            body_fallback_count=len(inline_groups),
            state="commented",
        )

    return PublishResult(
        review_url=_review_url(raw),
        inline_count=len(inline_groups),
        body_fallback_count=0,
        state="commented",
    )


def publish_body_review(
    *,
    run_dir: Path,
    repo: str,
    pr_number: int,
    body: str,
    execute: bool,
) -> PublishResult:
    """Persist and optionally send one body-only GitHub COMMENT review."""

    payload = _payload(body=body, inline_groups=[], outcome=None)
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
        review_url=_review_url(raw),
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
