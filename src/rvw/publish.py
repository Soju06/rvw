"""Publish file-first reports as GitHub reviews whose event and threads follow policy.

Inline-anchor fallback is deliberately bulk and bounded: publication first attempts
one review containing every inline anchor. If GitHub rejects that review with HTTP
422, all inline comments move under ``the inline-anchor fallback section`` in the review body and
the whole review is retried once. GitHub rejects the complete review when any one
anchor is invalid, while per-comment probing would cost N API calls; this strategy
is deterministic and capped at two calls.

The review event (COMMENT, REQUEST_CHANGES, APPROVE) comes from the repository's
``publish`` policy and the run's PASS/BLOCK verdict; anything uncertain (no verdict, a
degraded run, language fallback, unknown identity, failed reads, an unverified policy
snapshot) clamps to COMMENT and disables dismissal and thread resolution.

Thread reconciliation reads rvw's own earlier threads and reviews before the review is
posted and touches them only after the review write succeeded: a finding that persists
keeps its thread and is not posted inline again; a finding that is gone has its thread
resolved when every fail-safe rule in :mod:`rvw.threads` holds; anything uncertain stays
open.
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
from rvw.policy import PublishPolicy, PublishPolicySource, ThreadPolicy
from rvw.presentation import PresentationConfig
from rvw.publication import (
    failed_lane_ids,
    render_publication,
    render_publication_item,
    uncovered_regions,
)
from rvw.runtimes.codex import CodexRuntime, CodexRuntimeMode
from rvw.schema import Severity, Verdict
from rvw.store import RunHandle, StageMissing
from rvw.summary import (
    EventClampReason,
    InlinePolicyFacts,
    PublicationSkipped,
    PublishFacts,
    ThreadsSkippedReason,
)
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
    build_review_marker,
    diff_provider,
    fingerprint,
    graphql_error_types,
    parse_review_marker,
    read_review_threads,
    reconcile_threads,
    renamed_paths,
    reply_to_thread,
    resolve_thread,
    strip_markers,
)

if TYPE_CHECKING:
    from rvw.gate import GateVerdict

_HTTP_STATUS = re.compile(r"(?:HTTP\s+|status(?: code)?[=: ]+)(?P<status>[1-5][0-9]{2})", re.I)
_COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")
OWN_LOGIN_VARIABLE = "RVW_GITHUB_LOGIN"
MAX_REVIEW_PAGES = 20

PolicyVerdict = Literal["PASS", "BLOCK"]
EventOverride = Literal["comment", "request_changes", "approve"]
_OVERRIDE_EVENT: dict[str, ReviewEvent] = {
    "comment": "COMMENT",
    "request_changes": "REQUEST_CHANGES",
    "approve": "APPROVE",
}
_EVENT_STATE: dict[ReviewEvent, Literal["commented", "changes_requested", "approved"]] = {
    "COMMENT": "commented",
    "REQUEST_CHANGES": "changes_requested",
    "APPROVE": "approved",
}
_REST_STATE: dict[str, ReviewEvent] = {
    "COMMENTED": "COMMENT",
    "CHANGES_REQUESTED": "REQUEST_CHANGES",
    "APPROVED": "APPROVE",
}


class PublishResult(BaseModel):
    """Observable result of a dry-run or GitHub review publication."""

    model_config = ConfigDict(extra="forbid")

    review_url: str | None
    inline_count: int
    body_fallback_count: int
    state: Literal["commented", "changes_requested", "approved", "skipped"]
    language_fallback_used: bool = False
    event: ReviewEvent | None = "COMMENT"
    skipped: PublicationSkipped | None = None
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


class EventOverrideRejected(ValueError):
    """``--event`` asked for more than the policy selected; only downgrades are allowed."""

    reason = "event_override_exceeds_policy"

    def __init__(self, requested: str, selected: ReviewEvent | None) -> None:
        self.requested = requested
        self.selected = selected
        super().__init__(
            f"{self.reason}: --event {requested} exceeds the policy-selected event "
            f"{selected or 'none'}; only a downgrade to comment is permitted"
        )


def select_event(
    policy: PublishPolicy,
    verdict: PolicyVerdict | None,
    *,
    clamp: bool,
    has_prose: bool,
) -> ReviewEvent | None:
    """Map the policy verdict to a review event; ``None`` means publish no review.

    No verdict (interactive review) or any clamp yields COMMENT, today's behaviour.
    """

    if verdict is None or clamp:
        return "COMMENT"
    if verdict == "BLOCK":
        return "REQUEST_CHANGES" if policy.on_block == "request_changes" else "COMMENT"
    if policy.on_pass == "approve":
        return "APPROVE"
    if policy.on_pass == "none":
        return "COMMENT" if has_prose else None
    return "COMMENT"


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
    run_dir: Path, facts: PublishFacts, *, publication_skipped: PublicationSkipped | None = None
) -> None:
    """Persist what publication did into ``summary.json`` beside the language facts."""

    from rvw.store import _write_json

    summary = _load_execution_summary(run_dir, "en")
    summary.publish = facts
    summary.publication_skipped = publication_skipped
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
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            raise GitHubGraphQLError(f"GraphQL response is not JSON: {exc}") from exc
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


@dataclass(frozen=True)
class OwnReview:
    """One review rvw posted earlier, recognised by author identity and review marker."""

    id: int
    state: str
    head_sha: str
    event: ReviewEvent


def read_own_reviews(
    client: GitHubClient, repo: str, pr_number: int, identity: OwnIdentity
) -> list[OwnReview]:
    """rvw's own marked reviews on the pull request, every page."""

    reviews: list[OwnReview] = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        try:
            data = client.rest(
                "GET", f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100&page={page}"
            )
        except Exception as exc:
            raise GitHubReadError(f"reviews read failed: {exc}") from exc
        if not isinstance(data, list):
            raise GitHubReadError("reviews response is not a list")
        for item in data:
            if not isinstance(item, Mapping):
                continue
            marker = parse_review_marker(
                item.get("body") if isinstance(item.get("body"), str) else None
            )
            review_id = item.get("id")
            if (
                marker is None
                or not isinstance(review_id, int)
                or not identity.matches_user(item.get("user"))
            ):
                continue
            reviews.append(
                OwnReview(
                    id=review_id,
                    state=str(item.get("state", "")),
                    head_sha=marker.head_sha,
                    event=marker.event,
                )
            )
        if len(data) < 100:
            return reviews
    raise GitHubReadError("reviews pagination did not terminate")


def read_pull_request_head(client: GitHubClient, repo: str, pr_number: int) -> str:
    try:
        data = client.rest("GET", f"repos/{repo}/pulls/{pr_number}")
    except Exception as exc:
        raise GitHubReadError(f"pull request read failed: {exc}") from exc
    head = data.get("head") if isinstance(data, Mapping) else None
    sha = head.get("sha") if isinstance(head, Mapping) else None
    if not isinstance(sha, str) or _COMMIT_ID.fullmatch(sha) is None:
        raise GitHubReadError("pull request head is missing")
    return sha


def _confirmed_inline_groups(
    merged: MergeResult, outcome: AdjudicationOutcome | None, policy: PublishPolicy
) -> list[CollapseGroup]:
    if outcome is None or "review" not in policy.channels:
        return []
    ranks = {Severity.SUGGESTION: 0, Severity.WARNING: 1, Severity.BLOCKER: 2}
    groups = [
        group
        for group in merged.groups
        if outcome.verdicts.get(group.key) is Verdict.CONFIRMED
        and group.anchorable
        and group.line is not None
        and ranks[group.severity] >= ranks[Severity(policy.inline.severity_at_least)]
    ]
    if policy.inline.max_comments is not None:
        groups.sort(key=lambda group: (-ranks[group.severity], group.key))
        groups = groups[: policy.inline.max_comments]
    return groups


def publication_policy_facts(
    merged: MergeResult,
    outcome: AdjudicationOutcome | None,
    policy: PublishPolicy,
    *,
    inline_keys: frozenset[str] | None = None,
) -> PublishFacts:
    """Resolved placement facts, also available when no review write is requested."""
    if inline_keys is None:
        inline_keys = frozenset(g.key for g in _confirmed_inline_groups(merged, outcome, policy))
    return PublishFacts(
        channels=list(policy.channels),
        inline_policy=InlinePolicyFacts(
            **policy.inline.model_dump(),
            body_only_count=sum(
                group.key not in inline_keys
                for group in merged.groups
                if outcome is None or outcome.verdicts.get(group.key) is not Verdict.REJECTED
            ),
        ),
    )


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


def _payload(
    *,
    event: ReviewEvent,
    body: str | None,
    comments: list[dict[str, object]] | None = None,
    commit_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"event": event}
    if body is not None:
        payload["body"] = body
    if comments:
        payload["comments"] = comments
    if commit_id is not None:
        payload["commit_id"] = commit_id
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
        f"#### `{comment['path']}:{comment['line']}`\n\n"
        f"{strip_markers(str(comment['body'])).rstrip()}"
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
class _Gathered:
    """GitHub state gathered for one publication, or the reason it was not."""

    plan: ReconciliationPlan | None = None
    threads: list[ReviewThread] = field(default_factory=list)
    own_reviews: list[OwnReview] = field(default_factory=list)
    pr_head: str | None = None
    reason: ThreadsSkippedReason | None = None
    read_failed: bool = False

    @property
    def suppressed(self) -> frozenset[str]:
        return frozenset(self.plan.suppressed_inline) if self.plan is not None else frozenset()


def _gather(
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
) -> _Gathered:
    result = _Gathered()
    if not attempt:
        result.reason = "not_planned"
        return result
    if identity is None or github is None:
        result.reason = "login_unknown"
        return result
    try:
        target = run.load_target()
    except (StageMissing, ValueError, OSError):
        result.reason = "not_planned"
        return result
    try:
        result.pr_head = read_pull_request_head(github, repo, pr_number)
        result.own_reviews = read_own_reviews(github, repo, pr_number, identity)
        if thread_policy.resolve_on_fix or thread_policy.reuse_open_thread:
            threads = read_review_threads(github, repo, pr_number, identity)
        else:
            threads = []
            result.reason = "disabled_by_policy"
    except GitHubReadError:
        result.reason = "read_failed"
        result.read_failed = True
        result.own_reviews = []
        result.pr_head = None
        return result
    if result.reason == "disabled_by_policy":
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
        renamed_from=renamed_paths(target.diff),
        excluded_paths=frozenset(budget.excluded_files) if budget is not None else frozenset(),
        head_hunks=parse_hunks(target.diff),
        uncovered={lane.lane_id: frozenset(lane.uncovered) for lane in coverage},
        diff_hunks=diff_provider(github, repo, target.head_sha, cwd),
        degraded=degraded,
        resolve_on_fix=thread_policy.resolve_on_fix,
        reuse_open_thread=thread_policy.reuse_open_thread,
    )
    # Body-only findings participate in identity matching so their presence cannot
    # be mistaken for fix evidence or steal an inline finding's thread. They do
    # not participate in any reuse/supersession/write plan.
    result.threads = threads
    result.plan = reconcile_threads(threads, candidates, context)
    for candidate in candidates:
        if not candidate.inline:
            thread_id = result.plan.reused.pop(candidate.key, None)
            if thread_id is not None:
                result.plan.outcomes.pop(thread_id, None)
    # Changed evidence can prevent an exact match. Presence of a body-only finding
    # for this rule/path still withholds fix proof for an unmatched old thread.
    body_only_rules = {
        (candidate.rule_id, candidate.lane_id, candidate.path)
        for candidate in candidates
        if not candidate.inline
    }
    for thread in threads:
        marker = thread.marker
        if (
            marker is not None
            and thread.id in result.plan.resolve
            and (marker.rule_id, marker.lane_id, thread.path) in body_only_rules
        ):
            result.plan.resolve.remove(thread.id)
            result.plan._record(thread.id, "skipped_policy")
    return result


def _plan_payload(
    plan: ReconciliationPlan | None,
    *,
    event: ReviewEvent | None,
    skipped: PublicationSkipped | None,
    dismiss: Sequence[int],
) -> dict[str, object]:
    planned: dict[str, object] = {
        "event": event,
        "publication_skipped": skipped,
        "dismiss": list(dismiss),
    }
    if plan is None:
        return planned
    planned.update(
        {
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
    )
    return planned


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

    def failed(thread_id: str, exc: Exception) -> bool:
        """Record a failed write; ``True`` means stop touching threads altogether."""

        types = exc.types if isinstance(exc, GitHubGraphQLError) else []
        if "FORBIDDEN" in types:
            facts.threads_skipped_reason = "forbidden"
            return True
        if "NOT_FOUND" in types:
            facts.threads_skipped_missing.append(thread_id)
            return False
        # Rate limits, locked conversations, transport failures: the review is already live,
        # so the thread simply stays open and the failure is recorded, never re-raised.
        facts.threads_skipped_write_failed.append(thread_id)
        facts.threads_skipped_reason = "write_failed"
        return False

    for thread_id in plan.resolve:
        try:
            confirmed = resolve_thread(github, thread_id)
        except (PublishError, ValueError, OSError) as exc:
            if failed(thread_id, exc):
                return
            continue
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
        except (PublishError, ValueError, OSError) as exc:
            if failed(supersession.thread_id, exc):
                return
            continue
        if confirmed:
            facts.superseded_thread_ids.append(supersession.thread_id)


def _dismissable(reviews: Sequence[OwnReview], head_sha: str) -> list[OwnReview]:
    """rvw's own REQUEST_CHANGES reviews on earlier heads; never one on the current head."""

    return [
        review
        for review in reviews
        if review.state == "CHANGES_REQUESTED" and review.head_sha != head_sha
    ]


def _dismiss_reviews(
    *,
    github: GitHubClient,
    repo: str,
    pr_number: int,
    reviews: Sequence[OwnReview],
    message: str,
    facts: PublishFacts,
) -> None:
    for review in reviews:
        path = f"repos/{repo}/pulls/{pr_number}/reviews/{review.id}"
        try:
            github.rest("PUT", f"{path}/dismissals", {"message": message, "event": "DISMISS"})
        except (PublishError, ValueError, OSError):
            # 422 covers "already dismissed" but also every other validation failure; only
            # GitHub's own state says whether the block is really lifted.
            try:
                current = github.rest("GET", path)
            except (PublishError, ValueError, OSError):
                current = None
            state = current.get("state") if isinstance(current, Mapping) else None
            if state == "DISMISSED":
                facts.dismissed_review_ids.append(review.id)
            else:
                facts.dismiss_failed_review_ids.append(review.id)
            continue
        facts.dismissed_review_ids.append(review.id)


def _duplicate_on_head(
    reviews: Sequence[OwnReview], head_sha: str, event: ReviewEvent | None, new_inline: bool
) -> bool:
    on_head = [review for review in reviews if review.head_sha == head_sha]
    if event == "REQUEST_CHANGES":
        return any(
            review.event == "REQUEST_CHANGES" or review.state == "CHANGES_REQUESTED"
            for review in on_head
        )
    if event is None:
        return False
    return not new_inline and any(review.event == event for review in on_head)


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
    verdict: PolicyVerdict | None = None,
    publish_policy: PublishPolicy | None = None,
    policy_source: PublishPolicySource | None = None,
    policy_verified: bool = True,
    thread_policy: ThreadPolicy | None = None,
    event_override: EventOverride | None = None,
    plan_threads: bool = False,
    cwd: Path | None = None,
) -> PublishResult:
    """Build or execute one GitHub review from persisted run artifacts.

    Without ``identity`` and ``github`` no existing thread or review is read or touched
    and the event clamps to COMMENT. With them, reconciliation and the same-head and
    dismissal reads run when executing or when ``plan_threads`` asks a dry run to plan.
    """

    del report_md
    presentation = presentation or run.load_presentation()
    if locale is not None:
        presentation = presentation.model_copy(update={"locale": locale})
    locale = presentation.locale
    publish_policy = publish_policy or PublishPolicy()
    thread_policy = thread_policy or ThreadPolicy()
    if publish_policy.inline.max_comments == 0:
        thread_policy = ThreadPolicy(resolve_on_fix=False, reuse_open_thread=False)
    inline_groups = _confirmed_inline_groups(merged, outcome, publish_policy)
    if "review" not in publish_policy.channels:
        facts = publication_policy_facts(merged, outcome, publish_policy)
        facts.policy_source = policy_source
        facts.threads_skipped_reason = "disabled_by_policy"
        record_publish_facts(run.dir, facts, publication_skipped="review_channel_disabled")
        (run.dir / "publish-payload.json").write_text(
            _json_text({"event": None, "publication_skipped": "review_channel_disabled"}) + "\n",
            encoding="utf-8",
        )
        return PublishResult(
            review_url=None,
            inline_count=0,
            body_fallback_count=0,
            state="skipped",
            event=None,
            skipped="review_channel_disabled",
            facts=facts,
        )
    try:
        coverage = run.load_discover().coverage
    except StageMissing:
        coverage = []
    try:
        summary = run.load_summary()
    except StageMissing:
        summary = None
    try:
        head_sha: str | None = run.load_target().head_sha
    except (StageMissing, ValueError, OSError):
        head_sha = None
    degraded = summary is None or summary.status.value in {"failed", "degraded"}
    candidates = _candidates(merged, outcome, frozenset(group.key for group in inline_groups))
    gathered = _gather(
        run=run,
        repo=repo,
        pr_number=pr_number,
        identity=identity,
        github=github,
        thread_policy=thread_policy,
        candidates=candidates,
        coverage=coverage,
        # A policy that could only be read from the run's own snapshot may be forged; it
        # never earns a resolution.
        degraded=degraded or not policy_verified,
        attempt=execute or plan_threads,
        cwd=cwd,
    )
    posted_groups = [group for group in inline_groups if group.key not in gathered.suppressed]
    posted_keys = frozenset(group.key for group in posted_groups)
    synthesis = run.load_synthesis() if gate_verdict is None else None
    body = render_publication(
        merged=merged,
        outcome=outcome,
        coverage=coverage,
        presentation=presentation,
        synthesis=synthesis,
        inline_keys=posted_keys,
        summary=summary,
    )
    if gate_verdict is not None:
        from rvw.special_publication import render_gate_publication

        body = render_gate_publication(gate_verdict, merged, outcome, presentation)
    markers = {candidate.key: _marker_for(candidate) for candidate in candidates}
    comments: list[dict[str, object]] = []
    for group in posted_groups:
        text = render_publication_item(
            group,
            outcome,
            presentation=presentation,
            synthesis=synthesis,
            inline=True,
        )
        marker = markers.get(group.key)
        if marker is not None:
            text = f"{text}\n\n{marker}"
        comments.append({"path": group.file, "line": group.line, "side": "RIGHT", "body": text})
    fallback_body = _fallback_body(body, comments, locale)
    plan = gathered.plan
    replies = {
        item.thread_id: t("publish.superseded", locale, path=item.path, line=item.line)
        for item in (plan.supersede if plan is not None else [])
    }
    reply_ids = list(replies)
    dismiss_message = t("publish.dismissed", locale)
    protected_literals = list(failed_lane_ids(coverage))
    if synthesis is not None and outcome is not None:
        from rvw.synthesis import synthesis_protected_literals

        protected_literals.extend(synthesis_protected_literals(synthesis, merged, outcome))
    documents, fallback_used = _check_publication(
        [
            body,
            *(str(comment["body"]) for comment in comments),
            fallback_body,
            dismiss_message,
            *(replies[thread_id] for thread_id in reply_ids),
        ],
        run_dir=run.dir,
        locale=locale,
        rewriter=rewriter,
        allow_language_fallback=allow_language_fallback,
        # Lane and source identifiers are verbatim data, not publication prose.
        protected_literals=list(dict.fromkeys(protected_literals)),
    )
    body = documents[0]
    fallback_body = documents[1 + len(comments)]
    dismiss_message = documents[2 + len(comments)]
    for comment, rewritten in zip(comments, documents[1 : 1 + len(comments)], strict=True):
        comment["body"] = rewritten
    for thread_id, rewritten in zip(reply_ids, documents[3 + len(comments) :], strict=True):
        replies[thread_id] = rewritten

    # Event selection: every uncertainty clamps to COMMENT and disables merge-ward writes.
    clamp_reason: EventClampReason | None = None
    if verdict is None:
        clamp_reason = "no_verdict"
    elif outcome is None:
        # Without adjudication every finding is UNCERTAIN and the verdict is PASS by default;
        # that is not evidence for anything stronger than a COMMENT.
        clamp_reason = "no_adjudication"
    elif degraded or fallback_used:
        clamp_reason = "degraded"
    elif identity is None and (execute or plan_threads):
        clamp_reason = "login_unknown"
    elif gathered.read_failed:
        clamp_reason = "read_failed"
    elif not policy_verified:
        clamp_reason = "snapshot_unverified"
    clamp = clamp_reason is not None
    has_prose = (
        bool(candidates)
        or uncovered_regions(coverage) > 0
        or bool(failed_lane_ids(coverage))
        or degraded
    )
    # The clamp reason is recorded whenever a clamp applies, even when the policy would have
    # chosen COMMENT anyway, because the same clamp disables dismissal and resolution.
    event = select_event(publish_policy, verdict, clamp=clamp, has_prose=has_prose)
    if event_override is not None:
        wanted = _OVERRIDE_EVENT[event_override]
        if wanted != event:
            if wanted != "COMMENT" or event not in ("REQUEST_CHANGES", "APPROVE"):
                raise EventOverrideRejected(event_override, event)
            event = "COMMENT"
            clamp_reason = "event_override"
    reconciliation_degraded = (
        degraded or fallback_used or gathered.read_failed or not policy_verified
    )

    facts = _facts_from_plan(plan, identity=identity, reason=gathered.reason)
    placement = publication_policy_facts(merged, outcome, publish_policy, inline_keys=posted_keys)
    facts.channels = placement.channels
    facts.inline_policy = placement.inline_policy
    facts.event = event
    facts.policy_source = policy_source
    facts.event_clamped_reason = clamp_reason
    if plan is not None and reconciliation_degraded and facts.threads_skipped_reason is None:
        facts.threads_skipped_reason = "degraded"

    skipped: PublicationSkipped | None = None
    if gathered.pr_head is not None and head_sha is not None and gathered.pr_head != head_sha:
        skipped = "head_moved"
    elif event is None:
        skipped = "on_pass_none"
    elif head_sha is not None and _duplicate_on_head(
        gathered.own_reviews, head_sha, event, bool(posted_groups)
    ):
        skipped = "duplicate_review_same_head"

    dismiss_allowed = (
        verdict == "PASS"
        and publish_policy.dismiss_on_pass
        and not clamp
        and skipped != "head_moved"
        and head_sha is not None
    )
    to_dismiss = _dismissable(gathered.own_reviews, head_sha or "") if dismiss_allowed else []

    review_marker = (
        build_review_marker(head_sha=head_sha, event=event)
        if head_sha is not None and event is not None
        else None
    )
    marked_body = body if review_marker is None else f"{body.rstrip()}\n\n{review_marker}\n"
    marked_fallback = (
        fallback_body if review_marker is None else f"{fallback_body.rstrip()}\n\n{review_marker}\n"
    )
    payload_event: ReviewEvent = event or "COMMENT"
    if event == "APPROVE" and not has_prose:
        payload = _payload(event="APPROVE", body=review_marker, commit_id=head_sha)
        comments = []
    else:
        payload = _payload(
            event=payload_event, body=marked_body, comments=comments, commit_id=head_sha
        )
    payload_text = _json_text(payload)

    if not execute:
        planned = dict(payload)
        if gathered.reason != "not_planned":
            planned["plan"] = _plan_payload(
                plan, event=event, skipped=skipped, dismiss=[review.id for review in to_dismiss]
            )
        (run.dir / "publish-payload.json").write_text(f"{_json_text(planned)}\n", encoding="utf-8")
        record_publish_facts(run.dir, facts, publication_skipped=skipped)
        return PublishResult(
            review_url=None,
            inline_count=len(comments),
            body_fallback_count=0,
            state="skipped" if skipped is not None else _EVENT_STATE[payload_event],
            language_fallback_used=fallback_used,
            event=None if skipped is not None else event,
            skipped=skipped,
            facts=facts,
        )

    if skipped == "head_moved":
        facts.event = None
        record_publish_facts(run.dir, facts, publication_skipped=skipped)
        return PublishResult(
            review_url=None,
            inline_count=0,
            body_fallback_count=0,
            state="skipped",
            language_fallback_used=fallback_used,
            event=None,
            skipped=skipped,
            facts=facts,
        )

    review_url: str | None = None
    inline_posted = bool(comments)
    body_fallback_count = 0
    if skipped is None:
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
            if exc.status_code != 422 or not comments or outcome is None:
                raise
            fallback = _payload(event=payload_event, body=marked_fallback, commit_id=head_sha)
            raw = _run(command, _json_text(fallback))
            inline_posted = False
            body_fallback_count = len(posted_groups)
            facts.inline_policy.body_only_count += len(posted_groups)
        review_url = _review_url(raw, locale=locale)
    else:
        facts.event = None
        inline_posted = False

    try:
        if plan is not None and github is not None and not reconciliation_degraded:
            _apply_thread_writes(
                github=github,
                plan=plan,
                facts=facts,
                replies=replies,
                inline_posted=inline_posted,
            )
        if to_dismiss and github is not None:
            _dismiss_reviews(
                github=github,
                repo=repo,
                pr_number=pr_number,
                reviews=to_dismiss,
                message=dismiss_message,
                facts=facts,
            )
    finally:
        # The review write is the commit point: whatever happened afterwards is recorded.
        record_publish_facts(run.dir, facts, publication_skipped=skipped)
    return PublishResult(
        review_url=review_url,
        inline_count=0 if body_fallback_count or skipped else len(comments),
        body_fallback_count=body_fallback_count,
        state="skipped" if skipped is not None else _EVENT_STATE[payload_event],
        language_fallback_used=fallback_used,
        event=None if skipped is not None else event,
        skipped=skipped,
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
    payload = _payload(event="COMMENT", body=documents[0], commit_id=commit_id)
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
    "EventOverride",
    "EventOverrideRejected",
    "GhCliClient",
    "GitHubGraphQLError",
    "OwnReview",
    "PolicyVerdict",
    "PublishError",
    "PublishResult",
    "publish_body_review",
    "publish_review",
    "read_own_reviews",
    "read_pull_request_head",
    "record_publish_facts",
    "resolve_own_identity",
    "select_event",
]
