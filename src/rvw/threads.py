"""Finding identity across heads and reconciliation of rvw's own review threads.

Every inline comment rvw publishes ends with one invisible HTML comment, the marker,
that names the finding fingerprint, rule, and lane; every review body ends with a review
marker naming the head and event. On a later head the markers let rvw recognise its own
threads and reviews without trusting line numbers or a bare author login: a finding that is
gone is resolved, a finding that persists keeps its thread, and anything uncertain is left
alone.

The fingerprint is deliberately line-independent. It digests the rule, the path, and the
adjudication evidence after normalisation (whitespace runs, trailing punctuation, and
quoted line-number prefixes removed), so an unrelated edit above the flagged code does not
change the identity while a change to the flagged code does.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rvw.hunks import Hunk, hunk_for_line, parse_hunks

MARKER_VERSION = "rvw:v1"
_IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9._/-]*"
_MARKER = re.compile(
    r"<!--\s*rvw:v1\s+fp=(?P<fp>[0-9a-f]{16})\s+rule=(?P<rule>"
    + _IDENTIFIER
    + r")\s+lane=(?P<lane>"
    + _IDENTIFIER
    + r")\s*-->"
)
_REVIEW_MARKER = re.compile(
    r"<!--\s*rvw:v1\s+review\s+head=(?P<head>[0-9a-f]{40})"
    r"\s+event=(?P<event>COMMENT|REQUEST_CHANGES|APPROVE)\s*-->"
)
_ANY_MARKER = re.compile(r"[ \t]*<!--\s*rvw:v1\s[^<>]*-->")
# ``path:12:`` / ``12:`` / ``12|`` / ``L12`` prefixes that quote a source line number.
_LINE_PREFIX = re.compile(r"^(?:[^\s:|]+:)?L?\d+\s*[:|]\s?")
_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = re.compile(r"[\s.,;:!?]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")

ReviewEvent = Literal["COMMENT", "REQUEST_CHANGES", "APPROVE"]
ThreadOutcome = Literal[
    "reused",
    "superseded",
    "resolved",
    "ambiguous",
    "skipped_resolved",
    "skipped_lane_invalid",
    "skipped_same_head",
    "skipped_human_reply",
    "skipped_unverified",
    "skipped_uncovered",
    "skipped_degraded",
    "skipped_policy",
]
MappingKind = Literal["mapped", "deleted", "unavailable"]
MAX_THREAD_PAGES = 20
MAX_THREAD_COMMENTS = 50


class GitHubClient(Protocol):
    """Minimal GitHub transport used by publication; tests supply a fake."""

    def rest(self, method: str, path: str, payload: Mapping[str, object] | None = None) -> object:
        """Perform one REST call and return the decoded JSON body (``None`` for no body)."""
        ...

    def graphql(self, query: str, variables: Mapping[str, object]) -> object:
        """Perform one GraphQL call and return the decoded ``data`` object."""
        ...


class GitHubReadError(RuntimeError):
    """A read needed for reconciliation failed or was truncated; writes are clamped."""


@dataclass(frozen=True)
class OwnIdentity:
    """rvw's own GitHub actor in the two spellings GitHub uses.

    REST names an App as ``<slug>[bot]`` with ``type: Bot``; GraphQL names the same actor as
    a ``Bot`` whose ``login`` is the bare slug. Personal tokens are ``User`` in both.
    """

    login: str
    kind: Literal["bot", "user"]

    @classmethod
    def parse(cls, raw: str | None) -> OwnIdentity | None:
        value = (raw or "").strip()
        if not value:
            return None
        if value.endswith("[bot]"):
            bare = value.removesuffix("[bot]")
            return cls(bare, "bot") if bare else None
        return cls(value, "user")

    @classmethod
    def from_user(cls, user: Mapping[str, object]) -> OwnIdentity | None:
        login = user.get("login")
        if not isinstance(login, str) or not login.strip():
            return None
        identity = cls.parse(login)
        if identity is None:
            return None
        if user.get("type") == "Bot":
            return cls(identity.login, "bot")
        return identity

    @property
    def rest_login(self) -> str:
        return f"{self.login}[bot]" if self.kind == "bot" else self.login

    def matches_author(self, login: str | None, typename: str | None) -> bool:
        """Match a GraphQL ``author { login __typename }``."""

        if not login or login.removesuffix("[bot]") != self.login:
            return False
        if typename is None:
            return True
        return (typename == "Bot") == (self.kind == "bot")

    def matches_user(self, user: object) -> bool:
        """Match a REST ``user`` object."""

        if not isinstance(user, Mapping):
            return False
        login = user.get("login")
        if not isinstance(login, str) or login.removesuffix("[bot]") != self.login:
            return False
        kind = user.get("type")
        if kind is None:
            return True
        return (kind == "Bot") == (self.kind == "bot")


@dataclass(frozen=True)
class Marker:
    fingerprint: str
    rule_id: str
    lane_id: str


@dataclass(frozen=True)
class ReviewMarker:
    head_sha: str
    event: ReviewEvent


def normalize_evidence(evidence: str) -> str:
    """Drop everything that changes when the flagged code merely moves.

    Line-number prefixes on quoted lines, whitespace runs, trailing punctuation, and empty
    lines are removed; the remaining lines keep their order.
    """

    lines: list[str] = []
    for raw in evidence.splitlines():
        line = _LINE_PREFIX.sub("", raw.strip(), count=1)
        line = _WHITESPACE.sub(" ", line).strip()
        line = _TRAILING_PUNCTUATION.sub("", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def fingerprint(rule_id: str, path: str, evidence: str) -> str:
    """First 16 hex digits of SHA-256 over rule, path, and normalised evidence."""

    material = f"{rule_id}\n{path}\n{normalize_evidence(evidence)}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def build_marker(*, fingerprint: str, rule_id: str, lane_id: str) -> str:
    """Render the invisible marker appended to every published inline comment."""

    if not re.fullmatch(r"[0-9a-f]{16}", fingerprint):
        raise ValueError("fingerprint must be 16 lowercase hex digits")
    for label, value in (("rule", rule_id), ("lane", lane_id)):
        if not re.fullmatch(_IDENTIFIER, value):
            raise ValueError(f"{label} identifier cannot be carried in a marker: {value!r}")
    return f"<!-- {MARKER_VERSION} fp={fingerprint} rule={rule_id} lane={lane_id} -->"


def parse_marker(body: str) -> Marker | None:
    """Return the last rvw marker in a comment body, or ``None`` when there is none.

    rvw appends its marker last, so a marker quoted inside evidence or injected into prose
    earlier in the body cannot override it.
    """

    matches = list(_MARKER.finditer(body))
    if not matches:
        return None
    match = matches[-1]
    return Marker(
        fingerprint=match.group("fp"), rule_id=match.group("rule"), lane_id=match.group("lane")
    )


def build_review_marker(*, head_sha: str, event: ReviewEvent) -> str:
    """Render the invisible marker appended to every published review body."""

    if _SHA.fullmatch(head_sha) is None:
        raise ValueError("review marker head must be a 40-character lowercase SHA")
    return f"<!-- {MARKER_VERSION} review head={head_sha} event={event} -->"


def parse_review_marker(body: str | None) -> ReviewMarker | None:
    """Return the last rvw review marker in a review body."""

    matches = list(_REVIEW_MARKER.finditer(body or ""))
    if not matches:
        return None
    match = matches[-1]
    event = match.group("event")
    assert event in ("COMMENT", "REQUEST_CHANGES", "APPROVE")
    return ReviewMarker(head_sha=match.group("head"), event=event)  # type: ignore[arg-type]


def strip_markers(text: str) -> str:
    """Remove rvw markers; used where an inline body is moved into a review body."""

    return _ANY_MARKER.sub("", text)


class ReviewThread(BaseModel):
    """One pull-request review thread as read from GitHub, with its parsed marker."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    original_line: int | None = Field(default=None, ge=1)
    is_resolved: bool = False
    is_outdated: bool = False
    subject_type: Literal["LINE", "FILE"] | None = None
    author: str | None = None
    author_type: str | None = None
    original_commit: str | None = None
    body: str = ""
    human_engaged: bool = False

    @property
    def marker(self) -> Marker | None:
        return parse_marker(self.body)


class Candidate(BaseModel):
    """One non-rejected finding of the current run, inline-capable or body-only."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    rule_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    inline: bool = False


class Supersession(BaseModel):
    """An outdated thread whose finding continues at a mapped line on the new head."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    candidate_key: str
    path: str
    line: int


class ReconciliationPlan(BaseModel):
    """Everything publication must do to rvw's own threads around posting a review."""

    model_config = ConfigDict(extra="forbid")

    resolve: list[str] = Field(default_factory=list)
    supersede: list[Supersession] = Field(default_factory=list)
    reused: dict[str, str] = Field(default_factory=dict)
    suppressed_inline: list[str] = Field(default_factory=list)
    post_inline: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    skipped_resolved: list[str] = Field(default_factory=list)
    skipped_lane_invalid: list[str] = Field(default_factory=list)
    skipped_same_head: list[str] = Field(default_factory=list)
    skipped_human_reply: list[str] = Field(default_factory=list)
    skipped_unverified: list[str] = Field(default_factory=list)
    skipped_uncovered: list[str] = Field(default_factory=list)
    skipped_degraded: list[str] = Field(default_factory=list)
    skipped_policy: list[str] = Field(default_factory=list)
    outcomes: dict[str, ThreadOutcome] = Field(default_factory=dict)

    def _record(self, thread_id: str, outcome: ThreadOutcome) -> None:
        self.outcomes[thread_id] = outcome
        bucket = {
            "resolved": self.resolve,
            "ambiguous": self.ambiguous,
            "skipped_resolved": self.skipped_resolved,
            "skipped_lane_invalid": self.skipped_lane_invalid,
            "skipped_same_head": self.skipped_same_head,
            "skipped_human_reply": self.skipped_human_reply,
            "skipped_unverified": self.skipped_unverified,
            "skipped_uncovered": self.skipped_uncovered,
            "skipped_degraded": self.skipped_degraded,
            "skipped_policy": self.skipped_policy,
        }.get(outcome)
        if bucket is not None and thread_id not in bucket:
            bucket.append(thread_id)


@dataclass(frozen=True)
class LineMapping:
    kind: MappingKind
    line: int | None = None
    # The old line lies inside an edited hunk of the head-to-head diff.
    touched: bool = False


DiffHunks = Callable[[str, str], Sequence[Hunk] | None]
"""``(original_commit, path) -> hunks of git diff <original>..<head> -- path`` or ``None``."""


@dataclass(frozen=True)
class ReconciliationContext:
    """Everything reconciliation needs to know about the new head."""

    identity: OwnIdentity
    head_sha: str
    lane_valid: Mapping[str, bool]
    # ``None`` means the new head's changed paths are unknown; a thread then never counts
    # as having left the diff.
    changed_paths: frozenset[str] | None = frozenset()
    # Old names of files the head diff renamed; a thread on one has not left the diff.
    renamed_from: frozenset[str] = frozenset()
    excluded_paths: frozenset[str] = frozenset()
    head_hunks: Sequence[Hunk] = ()
    uncovered: Mapping[str, frozenset[str]] = field(default_factory=dict)
    diff_hunks: DiffHunks | None = None
    degraded: bool = False
    resolve_on_fix: bool = True
    reuse_open_thread: bool = True


def map_old_line(hunks: Sequence[Hunk], line: int) -> LineMapping:
    """Map an old-side line through unified-diff hunks to its new-side line."""

    offset = 0
    for hunk in sorted(hunks, key=lambda item: item.old_start):
        if hunk.old_count == 0:
            # A pure insertion is anchored after ``old_start``; that line itself is untouched.
            if line <= hunk.old_start:
                return LineMapping("mapped", line + offset)
            offset += hunk.new_count
            continue
        if line < hunk.old_start:
            return LineMapping("mapped", line + offset)
        if line < hunk.old_start + hunk.old_count:
            old, new = hunk.old_start, hunk.new_start
            for raw in hunk.raw_text.splitlines()[1:]:
                if raw.startswith("\\"):
                    continue
                if raw.startswith(" "):
                    if old == line:
                        return LineMapping("mapped", new, touched=True)
                    old += 1
                    new += 1
                elif raw.startswith("-"):
                    if old == line:
                        return LineMapping("deleted", touched=True)
                    old += 1
                elif raw.startswith("+"):
                    new += 1
            return LineMapping("deleted", touched=True)
        offset += hunk.new_count - hunk.old_count
    return LineMapping("mapped", line + offset)


_RENAME_FROM = re.compile(r"^rename from (.+)$", re.M)


def renamed_paths(diff: str) -> frozenset[str]:
    """Old names of files a unified diff renames (``rename from`` headers)."""

    return frozenset(match.group(1).strip() for match in _RENAME_FROM.finditer(diff))


def diff_hunks_from_text(diff: str, path: str) -> list[Hunk]:
    """Hunks of one unified diff restricted to ``path``."""

    return [hunk for hunk in parse_hunks(diff) if hunk.file == path]


def compare_hunks(
    client: GitHubClient, repo: str, base: str, head: str, path: str
) -> list[Hunk] | None:
    """Hunks of ``base..head`` for ``path`` through the compare API, or ``None``.

    The compare endpoint only diffs from the merge base, so the result is accepted only
    when ``base`` is that merge base (an ordinary push); a rebased or amended history is
    unavailable rather than wrong. The ``patch`` field carries no file headers, so they are
    synthesised before parsing.
    """

    try:
        data = client.rest("GET", f"repos/{repo}/compare/{base}...{head}")
    except Exception:
        return None
    if not isinstance(data, Mapping):
        return None
    merge_base = data.get("merge_base_commit")
    if not isinstance(merge_base, Mapping) or merge_base.get("sha") != base:
        return None
    files = data.get("files")
    if not isinstance(files, list):
        return None
    for entry in files:
        if not isinstance(entry, Mapping):
            continue
        filename = entry.get("filename")
        if not isinstance(filename, str):
            continue
        if filename == path or entry.get("previous_filename") == path:
            patch = entry.get("patch")
            if not isinstance(patch, str):
                return None
            diff = f"--- a/{path}\n+++ b/{filename}\n{patch}\n"
            return diff_hunks_from_text(diff, filename)
    # The compare list is capped at 300 files with no truncation flag, and the provider is
    # only consulted for outdated threads, whose file did change: absence is not evidence.
    return None


def local_hunks(cwd: Path, base: str, head: str, path: str) -> list[Hunk] | None:
    """Hunks of ``git diff base..head -- path`` when both commits exist locally."""

    try:
        for commit in (base, head):
            subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=cwd,
                check=True,
                capture_output=True,
            )
        diff = subprocess.run(
            [
                "git",
                "diff",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-relative",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                f"{base}..{head}",
                "--",
                f":(top,literal){path}",
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    hunks = diff_hunks_from_text(diff, path)
    if diff.strip() and not hunks:
        # Non-empty output we cannot parse (binary, mode-only, unknown driver): unavailable.
        return None
    return hunks


def diff_provider(
    client: GitHubClient | None, repo: str, head_sha: str, cwd: Path | None
) -> DiffHunks:
    """Prefer the local repository, then the compare API; cache per commit and path."""

    cache: dict[tuple[str, str], Sequence[Hunk] | None] = {}

    def provide(base: str, path: str) -> Sequence[Hunk] | None:
        key = (base, path)
        if key not in cache:
            hunks: Sequence[Hunk] | None = None
            if cwd is not None:
                hunks = local_hunks(cwd, base, head_sha, path)
            if hunks is None and client is not None:
                hunks = compare_hunks(client, repo, base, head_sha, path)
            cache[key] = hunks
        return cache[key]

    return provide


@dataclass
class _Group:
    threads: list[ReviewThread] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)


def _position(thread: ReviewThread, context: ReconciliationContext) -> LineMapping:
    if thread.subject_type == "FILE":
        return LineMapping("unavailable")
    if not thread.is_outdated and thread.line is not None:
        # GitHub tracks a live thread onto the current head; its region is unchanged.
        return LineMapping("mapped", thread.line)
    if (
        thread.original_line is not None
        and thread.original_commit is not None
        and context.diff_hunks is not None
    ):
        if thread.original_commit == context.head_sha:
            return LineMapping("mapped", thread.original_line)
        hunks = context.diff_hunks(thread.original_commit, thread.path)
        if hunks is not None:
            return map_old_line(hunks, thread.original_line)
    return LineMapping("unavailable")


def _resolution_outcome(
    thread: ReviewThread,
    marker: Marker,
    position: LineMapping,
    context: ReconciliationContext,
) -> ThreadOutcome:
    if context.degraded:
        return "skipped_degraded"
    if thread.original_commit == context.head_sha:
        return "skipped_same_head"
    if thread.human_engaged:
        return "skipped_human_reply"
    if not context.lane_valid.get(marker.lane_id, False):
        return "skipped_lane_invalid"
    left_the_diff = (
        context.changed_paths is not None
        and thread.path not in context.changed_paths
        and thread.path not in context.renamed_from
    )
    changed = thread.is_outdated or position.kind == "deleted" or position.touched
    if not (changed or left_the_diff):
        return "skipped_unverified"
    if thread.is_outdated and position.kind == "unavailable" and not left_the_diff:
        return "skipped_unverified"
    if thread.path in context.excluded_paths:
        return "skipped_uncovered"
    if position.kind == "mapped" and position.line is not None:
        hunk = hunk_for_line(list(context.head_hunks), thread.path, position.line)
        if hunk is not None and hunk.hunk_id in context.uncovered.get(marker.lane_id, ()):
            return "skipped_uncovered"
    if not context.resolve_on_fix:
        return "skipped_policy"
    return "resolved"


def reconcile_threads(
    threads: Iterable[ReviewThread],
    candidates: Iterable[Candidate],
    context: ReconciliationContext,
) -> ReconciliationPlan:
    """Decide, per rvw thread and per candidate, what publication does on the new head.

    Only threads carrying a marker and authored by rvw's own identity are considered.
    Matching runs the fingerprint step first (valid only for a unique fingerprint on the
    path), then the moved-line step per ``(rule_id, path)`` with a unique-pair fallback.
    Resolution requires a valid lane, evidence that the thread's region changed, coverage of
    that region, no same-head origin, no human reply, no clamp, and an unambiguous no-match;
    anything else leaves the thread untouched.
    """

    plan = ReconciliationPlan()
    own = [
        thread
        for thread in threads
        if thread.marker is not None
        and context.identity.matches_author(thread.author, thread.author_type)
    ]
    pending = list(candidates)
    matched: dict[str, str] = {}
    # Step 1: unique fingerprint on the same path. Open threads own a fingerprint; a resolved
    # thread matches only when no open thread carries it, so a superseded thread does not
    # disable the fast path for its successor.
    open_fps: dict[tuple[str, str], list[ReviewThread]] = {}
    resolved_fps: dict[tuple[str, str], list[ReviewThread]] = {}
    for thread in own:
        marker = thread.marker
        assert marker is not None
        bucket = resolved_fps if thread.is_resolved else open_fps
        bucket.setdefault((thread.path, marker.fingerprint), []).append(thread)
    candidate_fps: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in pending:
        candidate_fps.setdefault((candidate.path, candidate.fingerprint), []).append(candidate)
    unmatched_open: list[ReviewThread] = []
    for thread in own:
        marker = thread.marker
        assert marker is not None
        key = (thread.path, marker.fingerprint)
        if thread.is_resolved:
            same_threads = [] if key in open_fps else resolved_fps[key]
        else:
            same_threads = open_fps[key]
        same_candidates = candidate_fps.get(key, [])
        if len(same_threads) == 1 and len(same_candidates) == 1:
            candidate = same_candidates[0]
            matched[candidate.key] = thread.id
            if thread.is_resolved:
                plan._record(thread.id, "skipped_resolved")
            else:
                plan.outcomes[thread.id] = "reused"
                plan.reused[candidate.key] = thread.id
            continue
        if not thread.is_resolved:
            unmatched_open.append(thread)

    # Step 2: same rule and path, position mapped through the diff between heads.
    groups: dict[tuple[str, str], _Group] = {}
    for thread in unmatched_open:
        marker = thread.marker
        assert marker is not None
        groups.setdefault((marker.rule_id, thread.path), _Group()).threads.append(thread)
    for candidate in pending:
        if candidate.key in matched:
            continue
        groups.setdefault((candidate.rule_id, candidate.path), _Group()).candidates.append(
            candidate
        )
    positions: dict[str, LineMapping] = {}
    for group in groups.values():
        remaining_threads = list(group.threads)
        remaining_candidates = list(group.candidates)
        for thread in remaining_threads:
            positions[thread.id] = _position(thread, context)
        claims: dict[str, list[ReviewThread]] = {}
        for thread in remaining_threads:
            position = positions[thread.id]
            if position.kind != "mapped":
                continue
            for candidate in remaining_candidates:
                if candidate.line is not None and candidate.line == position.line:
                    claims.setdefault(candidate.key, []).append(thread)
        ambiguous_here: list[ReviewThread] = []
        for key, claimants in claims.items():
            candidate = next(item for item in remaining_candidates if item.key == key)
            if len(claimants) > 1:
                ambiguous_here.extend(item for item in claimants if item not in ambiguous_here)
                continue
            thread = claimants[0]
            if thread in ambiguous_here or thread not in remaining_threads:
                continue
            matched[candidate.key] = thread.id
            remaining_threads.remove(thread)
            remaining_candidates.remove(candidate)
            plan.outcomes[thread.id] = "reused"
            plan.reused[candidate.key] = thread.id
        for thread in ambiguous_here:
            if thread in remaining_threads:
                remaining_threads.remove(thread)
        if (
            not ambiguous_here
            and len(remaining_threads) == 1
            and len(remaining_candidates) == 1
            and positions[remaining_threads[0].id].kind != "deleted"
        ):
            # Exactly one open thread and one finding for this rule and path: the same one.
            thread, candidate = remaining_threads.pop(), remaining_candidates.pop()
            matched[candidate.key] = thread.id
            plan.outcomes[thread.id] = "reused"
            plan.reused[candidate.key] = thread.id
        unmappable = [
            thread for thread in remaining_threads if positions[thread.id].kind == "unavailable"
        ]
        if remaining_candidates and (ambiguous_here or len(unmappable) >= 2):
            for thread in unmappable:
                if thread not in ambiguous_here:
                    ambiguous_here.append(thread)
                remaining_threads.remove(thread)
        if ambiguous_here:
            for thread in ambiguous_here:
                plan._record(thread.id, "ambiguous")
            for candidate in remaining_candidates:
                matched[candidate.key] = ""
                if candidate.key not in plan.suppressed_inline and candidate.inline:
                    plan.suppressed_inline.append(candidate.key)
        # Whatever is left has no finding on the new head for this rule and path.
        for thread in remaining_threads:
            marker = thread.marker
            assert marker is not None
            plan._record(
                thread.id, _resolution_outcome(thread, marker, positions[thread.id], context)
            )

    # Already-resolved threads whose finding is gone would have been resolved; count them.
    for thread in own:
        marker = thread.marker
        assert marker is not None
        if not thread.is_resolved or thread.id in plan.outcomes:
            continue
        if context.lane_valid.get(marker.lane_id, False):
            plan._record(thread.id, "skipped_resolved")

    # Reuse suppresses the inline repost; an outdated thread is superseded instead.
    thread_by_id = {thread.id: thread for thread in own}
    candidate_by_key = {candidate.key: candidate for candidate in pending}
    for key, thread_id in list(plan.reused.items()):
        thread = thread_by_id[thread_id]
        candidate = candidate_by_key[key]
        if not context.reuse_open_thread:
            del plan.reused[key]
            plan.outcomes.pop(thread.id, None)
            continue
        if (
            thread.is_outdated
            and candidate.inline
            and candidate.line is not None
            and context.resolve_on_fix
            and not context.degraded
            and not thread.human_engaged
        ):
            plan.outcomes[thread.id] = "superseded"
            del plan.reused[key]
            plan.supersede.append(
                Supersession(
                    thread_id=thread.id,
                    candidate_key=candidate.key,
                    path=candidate.path,
                    line=candidate.line,
                )
            )
            continue
        # Reused (including an outdated thread whose supersession is withheld): the finding
        # stays in the body and is not posted inline again.
        if candidate.inline and key not in plan.suppressed_inline:
            plan.suppressed_inline.append(key)
    for key, thread_id in matched.items():
        thread = thread_by_id.get(thread_id)
        if thread is not None and thread.is_resolved and context.reuse_open_thread:
            candidate = candidate_by_key[key]
            if candidate.inline and key not in plan.suppressed_inline:
                plan.suppressed_inline.append(key)

    suppressed = set(plan.suppressed_inline)
    plan.post_inline = [
        candidate.key
        for candidate in pending
        if candidate.inline and candidate.key not in suppressed
    ]
    return plan


_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          subjectType
          path
          line
          originalLine
          comments(first: 50) {
            totalCount
            nodes {
              body
              author { login __typename }
              originalCommit { oid }
            }
          }
        }
      }
    }
  }
}
"""

_RESOLVE_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId, resolutionReason: ADDRESSED}) {
    thread { id isResolved }
  }
}
"""

_REPLY_MUTATION = """
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { id }
  }
}
"""


def _dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GitHubReadError(f"{label} is not an object")
    return value


def read_review_threads(
    client: GitHubClient, repo: str, pr_number: int, identity: OwnIdentity
) -> list[ReviewThread]:
    """Read every marker-bearing review thread of a pull request.

    Threads by other authors are kept (with their marker) so callers can observe them, but
    ``reconcile_threads`` ignores them; ``human_engaged`` is computed against ``identity``.
    """

    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise GitHubReadError(f"repository must be owner/name: {repo!r}")
    threads: list[ReviewThread] = []
    cursor: str | None = None
    for _page in range(MAX_THREAD_PAGES):
        try:
            response = client.graphql(
                _THREADS_QUERY,
                {"owner": owner, "name": name, "number": pr_number, "cursor": cursor},
            )
        except GitHubReadError:
            raise
        except Exception as exc:
            raise GitHubReadError(f"reviewThreads read failed: {exc}") from exc
        data = _dict(response, "reviewThreads response")
        repository = _dict(data.get("repository"), "repository")
        pull_request = _dict(repository.get("pullRequest"), "pullRequest")
        connection = _dict(pull_request.get("reviewThreads"), "reviewThreads")
        nodes = connection.get("nodes")
        if not isinstance(nodes, list):
            raise GitHubReadError("reviewThreads.nodes is not a list")
        for node in nodes:
            thread = _thread_from_node(_dict(node, "review thread"), identity)
            if thread is not None and thread.marker is not None:
                threads.append(thread)
        page = _dict(connection.get("pageInfo"), "pageInfo")
        if not page.get("hasNextPage"):
            return threads
        end_cursor = page.get("endCursor")
        if not isinstance(end_cursor, str) or not end_cursor:
            raise GitHubReadError("reviewThreads pagination cursor is missing")
        cursor = end_cursor
    raise GitHubReadError("reviewThreads pagination did not terminate")


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _subject_type(value: object) -> Literal["LINE", "FILE"] | None:
    if value == "LINE":
        return "LINE"
    if value == "FILE":
        return "FILE"
    return None


def _thread_from_node(node: dict[str, object], identity: OwnIdentity) -> ReviewThread | None:
    comments = _dict(node.get("comments"), "comments")
    nodes = comments.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    first = _dict(nodes[0], "first comment")
    author = first.get("author")
    login = author.get("login") if isinstance(author, dict) else None
    typename = author.get("__typename") if isinstance(author, dict) else None
    commit = first.get("originalCommit")
    oid = commit.get("oid") if isinstance(commit, dict) else None
    total = comments.get("totalCount")
    engaged = isinstance(total, int) and total > len(nodes)
    for later in nodes[1:]:
        later_author = _dict(later, "comment").get("author")
        later_login = later_author.get("login") if isinstance(later_author, dict) else None
        later_type = later_author.get("__typename") if isinstance(later_author, dict) else None
        if not identity.matches_author(
            later_login if isinstance(later_login, str) else None,
            later_type if isinstance(later_type, str) else None,
        ):
            engaged = True
    try:
        return ReviewThread(
            id=str(node.get("id", "")),
            path=str(node.get("path", "")),
            line=_optional_int(node.get("line")),
            original_line=_optional_int(node.get("originalLine")),
            is_resolved=bool(node.get("isResolved", False)),
            is_outdated=bool(node.get("isOutdated", False)),
            subject_type=_subject_type(node.get("subjectType")),
            author=login if isinstance(login, str) else None,
            author_type=typename if isinstance(typename, str) else None,
            original_commit=oid if isinstance(oid, str) else None,
            body=str(first.get("body", "")),
            human_engaged=engaged,
        )
    except ValueError as exc:
        raise GitHubReadError(f"review thread is malformed: {exc}") from exc


def resolve_thread(client: GitHubClient, thread_id: str) -> bool:
    """Resolve one thread as addressed; ``True`` only when GitHub confirms it."""

    response = client.graphql(_RESOLVE_MUTATION, {"threadId": thread_id})
    if not isinstance(response, dict):
        return False
    payload = response.get("resolveReviewThread")
    thread = payload.get("thread") if isinstance(payload, dict) else None
    return isinstance(thread, dict) and thread.get("isResolved") is True


def reply_to_thread(client: GitHubClient, thread_id: str, body: str) -> None:
    client.graphql(_REPLY_MUTATION, {"threadId": thread_id, "body": body})


def graphql_error_types(raw: str) -> list[str]:
    """Extract ``errors[].type`` from a GraphQL response body, tolerating anything else."""

    try:
        data = json.loads(raw)
    except ValueError:
        return []
    errors = data.get("errors") if isinstance(data, dict) else None
    if not isinstance(errors, list):
        return []
    return [
        str(error.get("type"))
        for error in errors
        if isinstance(error, dict) and error.get("type") is not None
    ]


__all__ = [
    "MARKER_VERSION",
    "MAX_THREAD_COMMENTS",
    "MAX_THREAD_PAGES",
    "Candidate",
    "DiffHunks",
    "GitHubClient",
    "GitHubReadError",
    "LineMapping",
    "Marker",
    "OwnIdentity",
    "ReconciliationContext",
    "ReconciliationPlan",
    "ReviewEvent",
    "ReviewMarker",
    "ReviewThread",
    "Supersession",
    "ThreadOutcome",
    "build_marker",
    "build_review_marker",
    "compare_hunks",
    "diff_hunks_from_text",
    "diff_provider",
    "fingerprint",
    "graphql_error_types",
    "local_hunks",
    "map_old_line",
    "normalize_evidence",
    "parse_marker",
    "parse_review_marker",
    "read_review_threads",
    "reconcile_threads",
    "renamed_paths",
    "reply_to_thread",
    "resolve_thread",
    "strip_markers",
]
