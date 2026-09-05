"""Deterministic, mechanical checks for lane scope authoring."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from rvw.lane import Lane, load_new_lane
from rvw.schema import Tier


@dataclass(frozen=True, slots=True)
class LaneLintDiagnostic:
    """Stable machine-readable lane lint diagnostic."""

    reason: str
    path: str
    line: int | None
    rule_id: str | None
    domain: str
    evidence: str
    severity: str
    message: str
    duplicate_of: str | None = None

    def payload(self) -> dict[str, object]:
        payload = asdict(self)
        if self.duplicate_of is None:
            payload.pop("duplicate_of")
        return payload


@dataclass(frozen=True, slots=True)
class _Marker:
    term: str
    domain: str


_FRONTEND_MARKERS = tuple(
    _Marker(term, "frontend")
    for term in (
        "component",
        "components",
        "hook",
        "hooks",
        "render",
        "CSS",
        "a11y",
        "React",
        "useEffect",
        "Tailwind",
        "skeleton",
        "Suspense",
        "accessibilityLabel",
        "hitSlop",
        "StyleSheet",
        "useScreenScrollInsets",
    )
)
_BACKEND_MARKERS = tuple(
    _Marker(term, "backend")
    for term in (
        "HTTP handler",
        "request id",
        "DB transaction",
        "migration",
        "transaction",
        "Prisma",
        "Atlas",
        "DDL",
        "DML",
        "server-side",
        "Doppler",
        "Wrangler",
    )
)
_LANGUAGE_MARKERS = (
    *(
        _Marker(term, "python")
        for term in (
            "except:",
            "except Exception",
            "# type: ignore",
            "dict[str, Any]",
            "dataclass",
            "Pydantic",
            "pytest",
        )
    ),
    *(
        _Marker(term, "typescript-javascript")
        for term in (
            "as any",
            "@ts-ignore",
            "@ts-expect-error",
            "z.coerce",
            "z.object",
            "z.union",
            "tsconfig",
        )
    ),
    *(_Marker(term, "go") for term in ("err != nil", "go.mod", "goroutine")),
    *(_Marker(term, "rust") for term in ("unwrap()", "Result<T", "Cargo.toml")),
)
_TOOL_MARKERS = tuple(
    _Marker(term, "llm-tools")
    for term in (
        "LLM tool",
        "agent-tool",
        "tool schema",
        "tool dispatch",
        "morphXML",
        "toolpack",
        "Zod",
    )
)
_ARTIFACT_MARKERS = tuple(
    _Marker(term, "test-ci-dependencies")
    for term in (
        "test that",
        "CI gate",
        "continue-on-error",
        "dependency manifest",
        "package.json",
        "pyproject.toml",
        "Gemfile",
    )
)
_BASE_MARKERS = (
    *_FRONTEND_MARKERS,
    *_BACKEND_MARKERS,
    *_LANGUAGE_MARKERS,
    *_TOOL_MARKERS,
    *_ARTIFACT_MARKERS,
)
_FRONTEND_OPPOSING = tuple(
    _Marker(term, "backend")
    for term in (
        "HTTP handler",
        "server",
        "DB",
        "DB transaction",
        "migration",
        "transaction",
        "Prisma",
        "Atlas",
        "DDL",
        "DML",
        "server-side",
        "SQL",
        "database",
    )
)
_BACKEND_OPPOSING = _FRONTEND_MARKERS
_PROCESS_MARKERS = tuple(
    _Marker(term, "process-style")
    for term in (
        "ask the owner",
        "approval",
        "same commit",
        "same PR",
        "write a changeset",
        "class-wide scan",
        "alphabetical order",
        "open with a verb",
        "해요체",
    )
)

_RULE_HEADING = re.compile(r"^##\s+rule:\s*(\S+)\s*$")
_RULE_GUIDANCE = re.compile(r"^\s*(?:-\s*)?`([^`]+)`\s*[—-]\s*(.*)$")
_INLINE_ALLOW = re.compile(r"<!--\s*lint-allow:\s*([^<>]+?)\s*-->", re.IGNORECASE)
_PLACEHOLDERS = {
    "rule is defined by lane guidance above",
    "the rule is defined by lane guidance above",
    "the rule is defined by the lane guidance above",
}
_BROAD_LANGUAGE_GLOB = re.compile(
    r"^(?:\*\*/)?\*\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|rs|java|rb)$",
    re.IGNORECASE,
)
_PACKAGED_BASE_ROOT = Path(__file__).parent / "lanes" / "base"


def _body_lines_with_offsets(path: Path) -> tuple[list[str], int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    closing = lines.index("---", 1)
    return lines[closing + 1 :], closing + 2


def _rule_attribution(lines: list[str], rules: set[str]) -> list[str | None]:
    attributed: list[str | None] = []
    heading_rule: str | None = None
    guidance_rule: str | None = None
    for line in lines:
        if heading := _RULE_HEADING.match(line):
            heading_rule = heading.group(1)
            guidance_rule = None
            attributed.append(heading_rule)
            continue
        if line.startswith("## "):
            heading_rule = None
            guidance_rule = None
        if guidance := _RULE_GUIDANCE.match(line):
            candidate = guidance.group(1)
            guidance_rule = candidate if candidate in rules else None
        attributed.append(heading_rule or guidance_rule)
    return attributed


def _term_occurs(line: str, marker: _Marker) -> bool:
    term = marker.term
    escaped = re.escape(term)
    prefix = r"(?<![\w-])" if term[0].isalnum() else ""
    suffix = r"(?![\w-])" if term[-1].isalnum() else ""
    flags = (
        0 if marker.domain in {"python", "typescript-javascript", "go", "rust"} else re.IGNORECASE
    )
    return re.search(prefix + escaped + suffix, line, flags) is not None


def _lane_domain(lane: Lane) -> str | None:
    searchable = " ".join(
        [lane.id, *(lane.when.paths if lane.when is not None and lane.when.paths else [])]
    ).casefold()
    if re.search(
        r"(?:^|[\s/_.-])(backend|server|workers?|observability)(?:$|[\s/_.-])", searchable
    ):
        return "backend"
    if re.search(r"(?:^|[\s/_.-])(frontend|mobile|web|skeleton|ui)(?:$|[\s/_.-])", searchable):
        return "frontend"
    return None


def _scope_term_diagnostics(path: Path, lane: Lane) -> list[LaneLintDiagnostic]:
    lines, first_line = _body_lines_with_offsets(path)
    attribution = _rule_attribution(lines, set(lane.rules))
    frontmatter_allowed = {
        term.casefold() for term in (lane.lint.allow_scope_terms if lane.lint is not None else [])
    }
    section_allows: list[set[str]] = []
    pending_allows: set[str] = set()
    active_allows: set[str] = set()
    in_rule = False
    for line in lines:
        local = {match.group(1).strip().casefold() for match in _INLINE_ALLOW.finditer(line)}
        if _RULE_HEADING.match(line):
            active_allows = set(pending_allows)
            pending_allows.clear()
            in_rule = True
        elif line.startswith("## "):
            active_allows.clear()
            pending_allows.clear()
            in_rule = False
        standalone_comment = bool(local) and not _INLINE_ALLOW.sub("", line).strip()
        if standalone_comment:
            if in_rule:
                active_allows.update(local)
            else:
                pending_allows.update(local)
        section_allows.append(set(active_allows if in_rule else pending_allows) | local)

    markers: tuple[_Marker, ...] = _PROCESS_MARKERS
    lane_domain = _lane_domain(lane)
    if lane.tier is Tier.BASE:
        markers += _BASE_MARKERS
    elif lane.tier is Tier.SCOPE and lane_domain == "frontend":
        markers += _FRONTEND_OPPOSING
    elif lane.tier is Tier.SCOPE and lane_domain == "backend":
        markers += _BACKEND_OPPOSING

    diagnostics: list[LaneLintDiagnostic] = []
    seen: set[tuple[int, str, str]] = set()
    for offset, line in enumerate(lines):
        if _RULE_HEADING.match(line):
            continue
        scan_line = _INLINE_ALLOW.sub("", line)
        if (guidance := _RULE_GUIDANCE.match(scan_line)) and guidance.group(1) in lane.rules:
            scan_line = guidance.group(2)
        for marker in markers:
            key = (offset, marker.domain, marker.term.casefold())
            if (
                marker.term.casefold() in frontmatter_allowed
                or marker.term.casefold() in section_allows[offset]
                or key in seen
                or not _term_occurs(scan_line, marker)
            ):
                continue
            seen.add(key)
            reason = (
                "non-code-rule" if marker.domain == "process-style" else "scope-domain-mismatch"
            )
            if lane.tier is Tier.BASE:
                scope_name = "base lane"
            elif lane_domain is not None:
                scope_name = f"{lane_domain} scope lane"
            else:
                scope_name = f"{lane.tier.value} lane"
            message = (
                f"code lane uses process/style term {marker.term!r}"
                if reason == "non-code-rule"
                else f"{scope_name} uses {marker.domain}-specific term {marker.term!r}"
            )
            diagnostics.append(
                LaneLintDiagnostic(
                    reason=reason,
                    path=str(path),
                    line=first_line + offset,
                    rule_id=attribution[offset],
                    domain=marker.domain,
                    evidence=marker.term,
                    severity="error",
                    message=message,
                )
            )
    return diagnostics


def _activation_diagnostics(path: Path, lane: Lane) -> list[LaneLintDiagnostic]:
    if lane.tier is not Tier.SCOPE or _lane_domain(lane) != "backend" or lane.when is None:
        return []
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    diagnostics: list[LaneLintDiagnostic] = []
    for pattern in lane.when.paths or ():
        if not _BROAD_LANGUAGE_GLOB.fullmatch(pattern):
            continue
        line_number = next(
            (index for index, line in enumerate(raw_lines, start=1) if pattern in line),
            None,
        )
        diagnostics.append(
            LaneLintDiagnostic(
                reason="scope-activation-too-broad",
                path=str(path),
                line=line_number,
                rule_id=None,
                domain="backend",
                evidence=pattern,
                severity="error",
                message=(
                    f"backend scope uses language-wide path {pattern!r}; "
                    "use backend directory predicates"
                ),
            )
        )
    return diagnostics


def _sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    sentence = re.sub(r"[`*_#]", "", sentence)
    sentence = re.sub(r"[^\w]+", " ", sentence.casefold())
    return " ".join(sentence.split())


def _rule_first_sentences(path: Path, lane: Lane) -> dict[str, tuple[str, int]]:
    lines, first_line = _body_lines_with_offsets(path)
    guidance: dict[str, tuple[str, int]] = {}
    headings: dict[str, int] = {}
    active_guidance: str | None = None
    guidance_parts: list[str] = []
    guidance_line = 0

    def finish_guidance() -> None:
        nonlocal active_guidance, guidance_parts
        if active_guidance is not None and guidance_parts:
            guidance[active_guidance] = (" ".join(guidance_parts), guidance_line)
        active_guidance = None
        guidance_parts = []

    for offset, line in enumerate(lines):
        if match := _RULE_GUIDANCE.match(line):
            finish_guidance()
            if match.group(1) in lane.rules and match.group(2).strip():
                active_guidance = match.group(1)
                guidance_parts = [match.group(2).strip()]
                guidance_line = first_line + offset
        elif active_guidance is not None:
            stripped = line.strip()
            if not stripped or stripped.startswith("-") or stripped.startswith("## "):
                finish_guidance()
            else:
                guidance_parts.append(stripped)
        if match := _RULE_HEADING.match(line):
            headings[match.group(1)] = offset
    finish_guidance()

    results: dict[str, tuple[str, int]] = {}
    for rule_id in lane.rules:
        heading_offset = headings[rule_id]
        paragraph: list[str] = []
        paragraph_line = first_line + heading_offset
        for offset in range(heading_offset + 1, len(lines)):
            line = lines[offset]
            if line.startswith("## "):
                break
            if not line.strip():
                if paragraph:
                    break
                continue
            if line.lstrip().startswith("<!--"):
                continue
            if not paragraph:
                paragraph_line = first_line + offset
            paragraph.append(line.strip())
        text = " ".join(paragraph)
        if _sentence(text) in _PLACEHOLDERS and rule_id in guidance:
            text, paragraph_line = guidance[rule_id]
        normalized = _sentence(text)
        if normalized and normalized not in _PLACEHOLDERS:
            results[rule_id] = (normalized, paragraph_line)
    return results


def _packaged_base_lanes() -> tuple[list[tuple[Path, Lane]], list[LaneLintDiagnostic]]:
    lanes: list[tuple[Path, Lane]] = []
    diagnostics: list[LaneLintDiagnostic] = []
    for path in sorted(_PACKAGED_BASE_ROOT.rglob("*.md")):
        try:
            lanes.append((path, load_new_lane(path)))
        except ValueError as error:
            message = str(error)
            reason = (
                "unsupported-glob-braces"
                if "unsupported-glob-braces" in message
                else "malformed-frontmatter"
            )
            diagnostics.append(
                LaneLintDiagnostic(
                    reason=reason,
                    path=str(path),
                    line=None,
                    rule_id=None,
                    domain="structure",
                    evidence="",
                    severity="error",
                    message=message,
                )
            )
    return lanes, diagnostics


def _duplicate_diagnostics(
    loaded: list[tuple[Path, Lane]],
) -> list[LaneLintDiagnostic]:
    base_by_id: dict[str, str] = {}
    base_by_sentence: dict[str, tuple[str, str]] = {}
    base_lanes, diagnostics = _packaged_base_lanes()
    base_lanes.extend(item for item in loaded if item[1].tier is Tier.BASE)
    for path, lane in base_lanes:
        sentences = _rule_first_sentences(path, lane)
        for rule_id in lane.rules:
            base_by_id.setdefault(rule_id, lane.id)
            if rule_id in sentences:
                base_by_sentence.setdefault(sentences[rule_id][0], (lane.id, rule_id))

    for path, lane in loaded:
        if lane.tier is not Tier.PROJECT:
            continue
        sentences = _rule_first_sentences(path, lane)
        body_lines, first_line = _body_lines_with_offsets(path)
        for rule_id in lane.rules:
            duplicate_rule: str | None = None
            duplicate_lane: str | None = None
            if rule_id in base_by_id:
                duplicate_rule = rule_id
                duplicate_lane = base_by_id[rule_id]
            elif rule_id in sentences and sentences[rule_id][0] in base_by_sentence:
                duplicate_lane, duplicate_rule = base_by_sentence[sentences[rule_id][0]]
            if duplicate_rule is None or duplicate_lane is None:
                continue
            heading_line = next(
                first_line + offset
                for offset, line in enumerate(body_lines)
                if (match := _RULE_HEADING.match(line)) and match.group(1) == rule_id
            )
            diagnostics.append(
                LaneLintDiagnostic(
                    reason="duplicate-rule-candidate",
                    path=str(path),
                    line=heading_line,
                    rule_id=rule_id,
                    domain="base-duplication",
                    evidence=rule_id if rule_id == duplicate_rule else sentences[rule_id][0],
                    severity="error",
                    message=(
                        f"project rule {rule_id!r} duplicates base rule "
                        f"{duplicate_rule!r} in lane {duplicate_lane!r}"
                    ),
                    duplicate_of=duplicate_rule,
                )
            )
    return diagnostics


def scope_diagnostics(loaded: list[tuple[Path, Lane]]) -> list[dict[str, object]]:
    """Return stable scope diagnostics for already validated lane documents."""

    diagnostics: list[LaneLintDiagnostic] = []
    for path, lane in loaded:
        diagnostics.extend(_scope_term_diagnostics(path, lane))
        diagnostics.extend(_activation_diagnostics(path, lane))
    diagnostics.extend(_duplicate_diagnostics(loaded))
    diagnostics.sort(
        key=lambda item: (item.path, item.line or 0, item.reason, item.domain, item.evidence)
    )
    return [item.payload() for item in diagnostics]
