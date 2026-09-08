"""Publish file-first reports as GitHub reviews whose inline threads live across heads.

Inline-anchor fallback is deliberately bulk and bounded: publication first attempts
one review containing every inline anchor. If GitHub rejects that review with HTTP
422, all inline comments move under ``the inline-anchor fallback section`` in the review body and
the whole review is retried once. GitHub rejects the complete review when any one
anchor is invalid, while per-comment probing would cost N API calls; this strategy
is deterministic and capped at two calls.

Thread reconciliation reads rvw's own earlier threads before the review is posted and
touches them only after the review write succeeded: a finding that persists keeps its
thread and is not posted inline again; a finding that is gone has its thread resolved when
every fail-safe rule in :mod:`rvw.threads` holds; anything uncertain stays open.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from rvw.adjudicate import AdjudicationOutcome
from rvw.hunks import parse_hunks
from rvw.i18n import Locale, t
from rvw.langgate import Rewriter, RuntimeRewriter, enforce_language_sync
from rvw.merge import CollapseGroup, MergeResult
from rvw.policy import ThreadPolicy
from rvw.presentation import PresentationConfig
from rvw.publication import failed_lane_ids, render_publication, render_publication_item
from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode
from rvw.schema import Verdict
from rvw.store import RunHandle, StageMissing
from rvw.summary import PublishFacts, ThreadsSkippedReason
from rvw.threads import (
    Candidate,
    GitHubClient,
    GitHubReadError,
    OwnIdentity,
    ReconciliationContext,
    ReconciliationPlan,
    ReviewEvent,
    ReviewThread,
    build_marker,
    diff_provider,
    fingerprint,
    graphql_error_types,
    read_review_threads,
    reconcile_threads,
    reply_to_thread,
    resolve_thread,
    strip_markers,
)

if TYPE_CHECKING:
    from rvw.gate import GateVerdict

_HTTP_STATUS = re.compile(r"(?:HTTP\s+|status(?: code)?[=: ]+)(?P<status>[1-5][0-9]{2})", re.I)
_COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")
OWN_LOGIN_VARIABLE = "RVW_GITHUB_LOGIN"


class PublishResult(BaseModel):
    """Observable result of a dry-run or GitHub review publication."""

    model_config = ConfigDict(extra="forbid")

    review_url: str | None
    inline_count: int
    body_fallback_count: int
    state: Literal["commented", "changes_requested", "approved", "skipped"]
    language_fallback_used: bool = False
    event: ReviewEvent | None = "COMMENT"
    skipped: str | None = None
    facts: PublishFacts | None = None


class PublishError(RuntimeError):
    """GitHub review creation failed."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


class GitHubGraphQLError(PublishError):
    """A GraphQL call returned ``errors``; ``types`` carries their ``type`` codes."""

    def __init__(self, detail: str, *, types: Sequence[str] = ()) -> None:
        self.types = list(types)
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
    summary = _load_execution_summary(run_dir, locale)
    summary.publication_failure = checked.failure_reason
    summary.language_fallback_used = checked.language_fallback_used
    _write_json(run_dir / "summary.json", summary.model_dump(mode="json"))
    if not checked.publishable:
        (run_dir / "publish-payload.json").unlink(missing_ok=True)
        raise PublicationLanguageMismatch(locale)
    return checked.documents, checked.language_fallback_used


def _load_execution_summary(run_dir: Path, locale: Locale):
    from rvw.summary import ExecutionSummary

    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        return ExecutionSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    presentation = RunHandle(run_dir.name, run_dir).load_presentation()
    return ExecutionSummary(presentation=presentation, markdown=t("pub.incomplete", locale))


def record_publish_facts(
    run_dir: Path, facts: PublishFacts, *, publication_skipped: str | None = None
) -> None:
    """Persist what publication did into ``summary.json`` beside the language facts."""

    from rvw.store import _write_json

    summary = _load_execution_summary(run_dir, "en")
    summary.publish = facts
    summary.publication_skipped = publication_skipped  # type: ignore[assignment]
    _write_json(run_dir / "summary.json", summary.model_dump(mode="json"))


def _run(cmd: list[str], input_json: str) -> str:
    """Execute one ``gh`` request that writes a review; kept as the publication test seam."""

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


def _gh(cmd: list[str], input_text: str | None) -> str:
    """Execute one ``gh api`` call for the GitHub client; a separate seam from ``_run``."""

    try:
        completed = subprocess.run(
            cmd,
            input=input_text,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = exc.stdout or ""
        types = graphql_error_types(stdout)
        if types or "graphql" in cmd:
            raise GitHubGraphQLError(stderr or stdout.strip() or str(exc), types=types) from exc
        match = _HTTP_STATUS.search(stderr or stdout)
        status = int(match.group("status")) if match is not None else None
        raise PublishError((stderr or stdout or str(exc)).strip(), status_code=status) from exc
    except OSError as exc:
        raise PublishError(str(exc)) from exc
    return completed.stdout


class GhCliClient:
    """GitHub transport through the authenticated ``gh`` CLI."""

    def rest(self, method: str, path: str, payload: Mapping[str, object] | None = None) -> object:
        cmd = ["gh", "api", "--method", method, path]
        text: str | None = None
        if payload is not None:
            cmd.extend(["--input", "-"])
            text = json.dumps(dict(payload), ensure_ascii=False)
        raw = _gh(cmd, text)
        return json.loads(raw) if raw.strip() else None

    def graphql(self, query: str, variables: Mapping[str, object]) -> object:
        body = json.dumps({"query": query, "variables": dict(variables)}, ensure_ascii=False)
        raw = _gh(["gh", "api", "graphql", "--input", "-"], body)
        data = json.loads(raw) if raw.strip() else {}
        errors = data.get("errors") if isinstance(data, dict) else None
        if errors:
            raise GitHubGraphQLError(
                "; ".join(
                    str(error.get("message", "")) for error in errors if isinstance(error, dict)
                )
                or "GraphQL request failed",
                types=graphql_error_types(raw),
            )
        return data.get("data") if isinstance(data, dict) else None


def resolve_own_identity(
    environ: Mapping[str, str] | None = None, *, client: GitHubClient | None = None
) -> OwnIdentity | None:
    """rvw's own GitHub actor: ``RVW_GITHUB_LOGIN`` first, then the token's user.

    An App installation token cannot describe itself, so the App passes the bot login
    through the environment; personal tokens fall back to ``GET /user``. ``None`` means
    publication must not touch any existing thread or review.
    """

    env = os.environ if environ is None else environ
    parsed = OwnIdentity.parse(env.get(OWN_LOGIN_VARIABLE))
    if parsed is not None:
        return parsed
    if client is None:
        return None
    try:
        user = client.rest("GET", "user")
    except Exception:
        return None
    return OwnIdentity.from_user(user) if isinstance(user, Mapping) else None


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


def _candidates(
    merged: MergeResult, outcome: AdjudicationOutcome | None, inline_keys: frozenset[str]
) -> list[Candidate]:
    """Every non-rejected finding of this run in the shape reconciliation matches on."""

    candidates: list[Candidate] = []
    for group in merged.groups:
        verdict = outcome.verdicts.get(group.key) if outcome is not None else None
        if verdict is Verdict.REJECTED or not group.lane_ids:
            continue
        evidence = outcome.evidence.get(group.key, "") if outcome is not None else ""
        candidates.append(
            Candidate(
                key=group.key,
                path=group.file,
                line=group.line,
                rule_id=group.rule_id,
                lane_id=group.lane_ids[0],
                fingerprint=fingerprint(group.rule_id, group.file, evidence),
                inline=group.key in inline_keys,
            )
        )
    return candidates


def _marker_for(candidate: Candidate) -> str | None:
    try:
        return build_marker(
            fingerprint=candidate.fingerprint,
            rule_id=candidate.rule_id,
            lane_id=candidate.lane_id,
        )
    except ValueError:
        return None


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
        f"#### `{comment['path']}:{comment['line']}`\n\n{strip_markers(str(comment['body'])).rstrip()}"
        for comment in comments
    ]
    return (
        body.rstrip()
        + "\n\n"
        + t("publish.fallback_heading", locale)
        + "\n\n"
        + "\n\n".join(items)
        + "\n"
    )


@dataclass
class _Reconciliation:
    """Thread state gathered for one publication."""

    plan: ReconciliationPlan | None = None
    threads: list[ReviewThread] = field(default_factory=list)
    reason: ThreadsSkippedReason | None = None
    degraded: bool = False

    @property
    def suppressed(self) -> frozenset[str]:
        return frozenset(self.plan.suppressed_inline) if self.plan is not None else frozenset()


def _reconcile(
    *,
    run: RunHandle,
    repo: str,
    pr_number: int,
    identity: OwnIdentity | None,
    github: GitHubClient | None,
    thread_policy: ThreadPolicy,
    candidates: Sequence[Candidate],
    coverage,
    degraded: bool,
    attempt: bool,
    cwd: Path | None,
) -> _Reconciliation:
    result = _Reconciliation(degraded=degraded)
    if not attempt:
        result.reason = "not_planned"
        return result
    if identity is None or github is None:
        result.reason = "login_unknown"
        return result
    if not (thread_policy.resolve_on_fix or thread_policy.reuse_open_thread):
        result.reason = "disabled_by_policy"
        return result
    try:
        target = run.load_target()
    except (StageMissing, ValueError, OSError):
        result.reason = "not_planned"
        return result
    try:
        threads = read_review_threads(github, repo, pr_number, identity)
    except GitHubReadError:
        result.reason = "read_failed"
        result.degraded = True
        return result
    try:
        budget = run.load_discover().budget
    except (StageMissing, ValueError, OSError, KeyError):
        budget = None
    context = ReconciliationContext(
        identity=identity,
        head_sha=target.head_sha,
        lane_valid={lane.lane_id: lane.valid > 0 for lane in coverage},
        changed_paths=frozenset(target.changed_paths),
        excluded_paths=frozenset(budget.excluded_files) if budget is not None else frozenset(),
        head_hunks=parse_hunks(target.diff),
        uncovered={lane.lane_id: frozenset(lane.uncovered) for lane in coverage},
        diff_hunks=diff_provider(github, repo, target.head_sha, cwd),
        degraded=degraded,
        resolve_on_fix=thread_policy.resolve_on_fix,
        reuse_open_thread=thread_policy.reuse_open_thread,
    )
    result.threads = threads
    result.plan = reconcile_threads(threads, candidates, context)
    return result


def _plan_payload(plan: ReconciliationPlan) -> dict[str, object]:
    return {
        "resolve": list(plan.resolve),
        "supersede": [item.model_dump(mode="json") for item in plan.supersede],
        "reuse": dict(plan.reused),
        "suppressed_inline": list(plan.suppressed_inline),
        "ambiguous": list(plan.ambiguous),
        "skipped": {
            name: getattr(plan, name)
            for name in (
                "skipped_resolved",
                "skipped_lane_invalid",
                "skipped_same_head",
                "skipped_human_reply",
                "skipped_unverified",
                "skipped_uncovered",
                "skipped_degraded",
                "skipped_policy",
            )
            if getattr(plan, name)
        },
    }


def _facts_from_plan(
    plan: ReconciliationPlan | None,
    *,
    identity: OwnIdentity | None,
    reason: ThreadsSkippedReason | None,
) -> PublishFacts:
    facts = PublishFacts(actor=identity.rest_login if identity is not None else None)
    facts.threads_skipped_reason = reason
    if plan is None:
        return facts
    facts.reused_thread_ids = sorted(set(plan.reused.values()))
    facts.threads_ambiguous = list(plan.ambiguous)
    facts.threads_skipped_lane_invalid = list(plan.skipped_lane_invalid)
    facts.threads_skipped_resolved = list(plan.skipped_resolved)
    facts.threads_skipped_same_head = list(plan.skipped_same_head)
    facts.threads_skipped_human_reply = list(plan.skipped_human_reply)
    facts.threads_skipped_unverified = list(plan.skipped_unverified) + list(plan.skipped_policy)
    facts.threads_skipped_uncovered = list(plan.skipped_uncovered)
    return facts


def _apply_thread_writes(
    *,
    github: GitHubClient,
    plan: ReconciliationPlan,
    facts: PublishFacts,
    replies: Mapping[str, str],
    inline_posted: bool,
) -> None:
    """Resolve fixed threads and supersede outdated ones after the review write succeeded."""

    for thread_id in plan.resolve:
        try:
            confirmed = resolve_thread(github, thread_id)
        except GitHubGraphQLError as exc:
            if "FORBIDDEN" in exc.types:
                facts.threads_skipped_reason = "forbidden"
                return
            if "NOT_FOUND" in exc.types:
                facts.threads_skipped_missing.append(thread_id)
                continue
            raise
        if confirmed:
            facts.resolved_thread_ids.append(thread_id)
    for supersession in plan.supersede:
        if not inline_posted:
            # The finding could not be re-anchored inline; keep the old thread open.
            facts.reused_thread_ids.append(supersession.thread_id)
            continue
        try:
            reply_to_thread(github, supersession.thread_id, replies[supersession.thread_id])
            confirmed = resolve_thread(github, supersession.thread_id)
        except GitHubGraphQLError as exc:
            if "FORBIDDEN" in exc.types:
                facts.threads_skipped_reason = "forbidden"
                return
            if "NOT_FOUND" in exc.types:
                facts.threads_skipped_missing.append(supersession.thread_id)
                continue
            raise
        if confirmed:
            facts.superseded_thread_ids.append(supersession.thread_id)


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
    identity: OwnIdentity | None = None,
    github: GitHubClient | None = None,
    thread_policy: ThreadPolicy | None = None,
    plan_threads: bool = False,
    cwd: Path | None = None,
) -> PublishResult:
    """Build or execute one GitHub review from persisted run artifacts.

    Without ``identity`` and ``github`` no existing thread is read or touched. With them,
    reconciliation runs when executing or when ``plan_threads`` asks a dry run to plan.
    """

    del report_md
    presentation = presentation or run.load_presentation()
    if locale is not None:
        presentation = presentation.model_copy(update={"locale": locale})
    locale = presentation.locale
    thread_policy = thread_policy or ThreadPolicy()
    inline_groups = _confirmed_inline_groups(merged, outcome)
    try:
        coverage = run.load_discover().coverage
    except StageMissing:
        coverage = []
    try:
        summary = run.load_summary()
    except StageMissing:
        summary = None
    degraded = summary is None or summary.status.value in {"failed", "degraded"}
    candidates = _candidates(merged, outcome, frozenset(group.key for group in inline_groups))
    reconciliation = _reconcile(
        run=run,
        repo=repo,
        pr_number=pr_number,
        identity=identity,
        github=github,
        thread_policy=thread_policy,
        candidates=candidates,
        coverage=coverage,
        degraded=degraded,
        attempt=execute or plan_threads,
        cwd=cwd,
    )
    posted_groups = [group for group in inline_groups if group.key not in reconciliation.suppressed]
    posted_keys = frozenset(group.key for group in posted_groups)
    body = render_publication(
        merged=merged,
        outcome=outcome,
        coverage=coverage,
        presentation=presentation,
        excluded_keys=posted_keys,
        summary=summary,
    )
    if gate_verdict is not None:
        from rvw.special_publication import render_gate_publication

        body = render_gate_publication(gate_verdict, merged, outcome, presentation)
    markers = {candidate.key: _marker_for(candidate) for candidate in candidates}
    comments: list[dict[str, object]] = []
    for group in posted_groups:
        text = render_publication_item(group, outcome, presentation=presentation, inline=True)
        marker = markers.get(group.key)
        if marker is not None:
            text = f"{text}\n\n{marker}"
        comments.append({"path": group.file, "line": group.line, "side": "RIGHT", "body": text})
    fallback_body = _fallback_body(body, comments, locale)
    plan = reconciliation.plan
    replies = {
        item.thread_id: t("publish.superseded", locale, path=item.path, line=item.line)
        for item in (plan.supersede if plan is not None else [])
    }
    reply_ids = list(replies)
    documents, fallback_used = _check_publication(
        [
            body,
            *(str(comment["body"]) for comment in comments),
            fallback_body,
            *(replies[thread_id] for thread_id in reply_ids),
        ],
        run_dir=run.dir,
        locale=locale,
        rewriter=rewriter,
        allow_language_fallback=allow_language_fallback,
        # Lane identifiers named by the failed-lanes sentence are data, not prose.
        protected_literals=failed_lane_ids(coverage),
    )
    body = documents[0]
    fallback_body = documents[1 + len(comments)]
    for comment, rewritten in zip(comments, documents[1 : 1 + len(comments)], strict=True):
        comment["body"] = rewritten
    for thread_id, rewritten in zip(reply_ids, documents[2 + len(comments) :], strict=True):
        replies[thread_id] = rewritten
    payload = _payload(body=body, comments=comments)
    payload_text = _json_text(payload)
    facts = _facts_from_plan(plan, identity=identity, reason=reconciliation.reason)
    facts.event = "COMMENT"
    if fallback_used and reconciliation.plan is not None:
        # Mismatched prose is a degraded outcome: never resolve on its strength.
        reconciliation.degraded = True
        facts.threads_skipped_reason = "degraded"

    if not execute:
        planned = dict(payload)
        if plan is not None:
            planned["plan"] = _plan_payload(plan)
        (run.dir / "publish-payload.json").write_text(f"{_json_text(planned)}\n", encoding="utf-8")
        return PublishResult(
            review_url=None,
            inline_count=len(posted_groups),
            body_fallback_count=0,
            state="commented",
            language_fallback_used=fallback_used,
            facts=facts,
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
    inline_posted = bool(comments)
    body_fallback_count = 0
    try:
        raw = _run(command, payload_text)
    except PublishError as exc:
        if exc.status_code != 422 or not comments or outcome is None:
            raise
        fallback = _payload(body=fallback_body)
        raw = _run(command, _json_text(fallback))
        inline_posted = False
        body_fallback_count = len(posted_groups)
    review_url = _review_url(raw, locale=locale)

    if plan is not None and github is not None and not reconciliation.degraded:
        _apply_thread_writes(
            github=github, plan=plan, facts=facts, replies=replies, inline_posted=inline_posted
        )
    elif plan is not None and reconciliation.degraded and facts.threads_skipped_reason is None:
        facts.threads_skipped_reason = "degraded"
    record_publish_facts(run.dir, facts)
    return PublishResult(
        review_url=review_url,
        inline_count=0 if body_fallback_count else len(posted_groups),
        body_fallback_count=body_fallback_count,
        state="commented",
        language_fallback_used=fallback_used,
        facts=facts,
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
    "OWN_LOGIN_VARIABLE",
    "GhCliClient",
    "GitHubGraphQLError",
    "PublishError",
    "PublishResult",
    "publish_body_review",
    "publish_review",
    "record_publish_facts",
    "resolve_own_identity",
]
