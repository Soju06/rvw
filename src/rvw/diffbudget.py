"""Generated-path filtering and ordered file-chunk planning for review diffs."""

from __future__ import annotations

import ast
import fnmatch
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_GENERATED_GLOBS = [
    "**/runtime-snapshots/**",
    "**/*.generated.*",
    "**/generated/**",
    "**/*.lock",
    "**/package-lock.json",
    "**/bun.lockb",
    "**/pnpm-lock.yaml",
    "**/dist/**",
    "**/__snapshots__/**",
]
"""Generated-file globs; a future registry may override this default list."""

_DIFF_HEADER = re.compile(r"^diff --git .+$", re.MULTILINE)
_OLD_FILE_HEADER = re.compile(r"^--- (?P<path>.+)$", re.MULTILINE)
_NEW_FILE_HEADER = re.compile(r"^\+\+\+ (?P<path>.+)$", re.MULTILINE)


class DiffChunkPlacement(BaseModel):
    """Persisted file placement and character accounting for one diff chunk."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    files: list[str]
    chars: int = Field(ge=0)


class DiffChunk(DiffChunkPlacement):
    """One prompt-sized group of complete, ordered per-file diff segments."""

    text: str


class DiffBudgetReport(BaseModel):
    """Character accounting, exclusions, and chunk placement for one review diff."""

    model_config = ConfigDict(extra="forbid")

    kept_files: list[str]
    excluded_files: list[str]
    excluded_reason: dict[str, str]
    kept_chars: int = Field(ge=0)
    excluded_chars: int = Field(ge=0)
    chunk_count: int = Field(ge=1)
    chunks: list[DiffChunkPlacement]

    @model_validator(mode="after")
    def _placement_must_match_totals(self) -> DiffBudgetReport:
        if self.chunk_count != len(self.chunks):
            raise ValueError("chunk_count must equal the number of chunk placements")
        if [chunk.index for chunk in self.chunks] != list(range(1, self.chunk_count + 1)):
            raise ValueError("chunk placement indexes must be contiguous from 1")
        if [file for chunk in self.chunks for file in chunk.files] != self.kept_files:
            raise ValueError("chunk placements must contain every kept file in order")
        if sum(chunk.chars for chunk in self.chunks) != self.kept_chars:
            raise ValueError("chunk placement characters must equal kept_chars")
        return self


class EmptyReviewDiffError(ValueError):
    """A diff budget retained no content that can be reviewed."""

    error_code = "empty-review-diff"

    def __init__(self, source: str, report: DiffBudgetReport) -> None:
        self.source = source
        self.excluded_reason = dict(report.excluded_reason)
        excluded = ", ".join(
            f"{path} ({report.excluded_reason[path]})" for path in report.excluded_files
        )
        super().__init__(f"{source} produced an empty review diff; excluded: [{excluded}]")

    def payload(self) -> dict[str, object]:
        """Return the stable machine-readable representation."""

        return {
            "error": self.error_code,
            "message": str(self),
            "excluded_reason": self.excluded_reason,
        }


@dataclass(frozen=True)
class DiffFileSegment:
    """One complete per-file unified-diff segment."""

    file: str
    text: str


def _header_path(raw: str) -> str | None:
    path = raw.split("\t", maxsplit=1)[0]
    if path == "/dev/null":
        return None
    if path.startswith('"') and path.endswith('"'):
        decoded = ast.literal_eval(path)
        if isinstance(decoded, str):
            path = decoded
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _segment_path(segment: str) -> str:
    old_match = _OLD_FILE_HEADER.search(segment)
    new_match = _NEW_FILE_HEADER.search(segment)
    old_path = _header_path(old_match.group("path")) if old_match else None
    new_path = _header_path(new_match.group("path")) if new_match else None
    if new_path or old_path:
        return new_path or old_path or ""

    first_line = next(
        (line for line in segment.splitlines() if line.startswith("diff --git ")),
        None,
    )
    if first_line is not None:
        parts = shlex.split(first_line)
        if len(parts) >= 4:
            fallback = _header_path(parts[3])
            if fallback is not None:
                return fallback
    raise ValueError("unified diff segment has no identifiable file path")


def split_diff_files(diff: str) -> list[DiffFileSegment]:
    """Split a unified diff into complete file segments with exact accounting."""

    if not diff:
        return []
    starts = [match.start() for match in _DIFF_HEADER.finditer(diff)]
    if not starts:
        starts = [match.start() for match in _OLD_FILE_HEADER.finditer(diff)]
    if not starts:
        raise ValueError("diff contains no per-file headers")

    chunks: list[str] = []
    for index, start in enumerate(starts):
        segment_start = 0 if index == 0 else start
        segment_end = starts[index + 1] if index + 1 < len(starts) else len(diff)
        chunks.append(diff[segment_start:segment_end])

    combined: dict[str, str] = {}
    for chunk in chunks:
        path = _segment_path(chunk)
        combined[path] = f"{combined.get(path, '')}{chunk}"
    return [DiffFileSegment(file=path, text=text) for path, text in combined.items()]


def _matches_generated_glob(path: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
            return True
    return False


def _exclusion_header(excluded_files: Sequence[str]) -> str:
    """Render the one visible exclusion header shared by every review prompt."""

    if not excluded_files:
        return ""
    paths = ", ".join(excluded_files)
    return (
        f"# rvw: {len(excluded_files)} files excluded from review diff "
        f"(generated/oversize): {paths}\n"
    )


def apply_diff_budget(
    diff: str,
    *,
    generated_globs: Sequence[str] = DEFAULT_GENERATED_GLOBS,
    max_file_chars: int = 200_000,
    max_total_chars: int = 400_000,
) -> tuple[list[DiffChunk], DiffBudgetReport]:
    """Filter excluded files, then plan ordered prompt-sized file chunks."""

    if max_file_chars < 0 or max_total_chars < 0:
        raise ValueError("diff budget limits must be non-negative")
    if max_file_chars > max_total_chars:
        raise ValueError("max_file_chars must not exceed max_total_chars")

    segments = split_diff_files(diff)
    kept: list[DiffFileSegment] = []
    excluded: list[DiffFileSegment] = []
    reasons: dict[str, str] = {}
    for segment in segments:
        if _matches_generated_glob(segment.file, generated_globs):
            excluded.append(segment)
            reasons[segment.file] = "generated-path"
        elif len(segment.text) > max_file_chars:
            excluded.append(segment)
            reasons[segment.file] = "oversize-file"
        else:
            kept.append(segment)

    grouped: list[list[DiffFileSegment]] = []
    current: list[DiffFileSegment] = []
    current_chars = 0
    for segment in kept:
        segment_chars = len(segment.text)
        if current and current_chars + segment_chars > max_total_chars:
            grouped.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += segment_chars
    if current or not grouped:
        grouped.append(current)

    header = _exclusion_header([segment.file for segment in excluded])

    chunks = [
        DiffChunk(
            index=index,
            files=[segment.file for segment in group],
            chars=sum(len(segment.text) for segment in group),
            text=f"{header}{''.join(segment.text for segment in group)}",
        )
        for index, group in enumerate(grouped, start=1)
    ]

    report = DiffBudgetReport(
        kept_files=[segment.file for segment in kept],
        excluded_files=[segment.file for segment in excluded],
        excluded_reason=reasons,
        kept_chars=sum(chunk.chars for chunk in chunks),
        excluded_chars=sum(len(segment.text) for segment in excluded),
        chunk_count=len(chunks),
        chunks=[
            DiffChunkPlacement(index=chunk.index, files=chunk.files, chars=chunk.chars)
            for chunk in chunks
        ],
    )
    return chunks, report


def require_reviewable_diff(report: DiffBudgetReport, *, source: str) -> None:
    """Fail when exclusions leave no characters for a runtime to review."""

    if report.kept_chars == 0:
        raise EmptyReviewDiffError(source, report)


@dataclass(frozen=True)
class ReviewedDiff:
    """The unpartitioned budget-filtered diff plus its exclusion accounting."""

    text: str
    report: DiffBudgetReport


def reviewed_diff(
    diff: str,
    *,
    generated_globs: Sequence[str] = DEFAULT_GENERATED_GLOBS,
    max_file_chars: int = 200_000,
    max_total_chars: int = 400_000,
) -> ReviewedDiff:
    """Project every kept segment behind one exclusion header without chunking.

    Post-discovery stages verify one candidate against the reviewed content and
    may need any kept file to do so, so they receive the retained diff whole
    rather than one chunk. Sharing this projection with ``apply_diff_budget``
    keeps a single owner for exclusion policy: an adjudication prompt can never
    contain a path that discovery was not allowed to review.

    The planner repeats the exclusion header on every chunk so each lane prompt
    is self-describing. Joining chunk text would therefore restate that header
    once per chunk, so this projection rebuilds the retained segments directly
    and states the header exactly once.
    """

    _chunks, report = apply_diff_budget(
        diff,
        generated_globs=generated_globs,
        max_file_chars=max_file_chars,
        max_total_chars=max_total_chars,
    )
    kept = set(report.kept_files)
    retained = "".join(segment.text for segment in split_diff_files(diff) if segment.file in kept)
    return ReviewedDiff(text=f"{_exclusion_header(report.excluded_files)}{retained}", report=report)


__all__ = [
    "DEFAULT_GENERATED_GLOBS",
    "DiffBudgetReport",
    "DiffChunk",
    "DiffChunkPlacement",
    "DiffFileSegment",
    "EmptyReviewDiffError",
    "ReviewedDiff",
    "apply_diff_budget",
    "require_reviewable_diff",
    "reviewed_diff",
    "split_diff_files",
]
