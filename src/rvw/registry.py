"""Typed registry loading and layer activation."""

from __future__ import annotations

import fnmatch
import posixpath
import subprocess
import tempfile
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from rvw.lane import Lane, load_lane, load_new_lane, validate_glob_patterns
from rvw.schema import Tier

if TYPE_CHECKING:
    from rvw.target import ResolvedTarget

if TYPE_CHECKING:
    from rvw.policy import AutoPolicy

TIER_ORDER = (Tier.BASE, Tier.PROJECT, Tier.SCOPE, Tier.DYNAMIC)


def _glob_match(path: str, pattern: str) -> bool:
    """Match normalized POSIX paths, allowing ``**`` to cross directories.

    For example, ``apps/agent-backend/**`` matches any file beneath that
    directory, at any depth.
    """

    normalized_path = posixpath.normpath(path.replace("\\", "/"))
    normalized_pattern = posixpath.normpath(pattern.replace("\\", "/"))
    candidate_patterns = [normalized_pattern]
    root_pattern = normalized_pattern
    while root_pattern.startswith("**/"):
        root_pattern = root_pattern[3:]
        candidate_patterns.append(root_pattern)
    return any(fnmatch.fnmatchcase(normalized_path, candidate) for candidate in candidate_patterns)


def _repo_match(repo: str, patterns: str | list[str]) -> bool:
    """Match a repository against one or more case-sensitive glob patterns."""

    if isinstance(patterns, str):
        patterns = [patterns]
    return any(fnmatch.fnmatchcase(repo, pattern) for pattern in patterns)


class LayerPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str | list[str] | None = None
    paths: list[str] | None = None

    _validate_paths = field_validator("paths")(validate_glob_patterns)


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tier: Tier
    lanes: list[str]
    when: LayerPredicate | None = None


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: list[Layer]

    def activate(self, repo: str, changed_paths: list[str]) -> list[Layer]:
        """Return activated layers in fixed tier order."""

        active = [
            layer
            for layer in self.layers
            if layer.when is None
            or (
                (layer.when.repo is None or _repo_match(repo, layer.when.repo))
                and (
                    layer.when.paths is None
                    or any(
                        _glob_match(path, pattern)
                        for path in changed_paths
                        for pattern in layer.when.paths
                    )
                )
            )
        ]
        return sorted(active, key=lambda layer: TIER_ORDER.index(layer.tier))


def load_registry(path: Path) -> Registry:
    """Load and validate a YAML layer registry."""

    return Registry.model_validate(yaml.safe_load(path.read_text()))


@dataclass(frozen=True)
class LaneSource:
    lane: Lane
    path: Path
    source: str


class EffectiveRegistry:
    """Registry facade for packaged and base-ref repository lane documents."""

    def __init__(self, sources: Iterable[LaneSource]) -> None:
        self.sources = tuple(sources)
        self._by_id = {item.lane.id: item for item in self.sources}

    def activate(self, repo: str, changed_paths: list[str]) -> list[Layer]:
        del repo
        active: list[Layer] = []
        for item in self._by_id.values():
            lane = item.lane
            if lane.tier in {Tier.BASE, Tier.DYNAMIC}:
                matches = True
            else:
                patterns = lane.when.paths if lane.when is not None else None
                matches = patterns is None or any(
                    _glob_match(path, pattern) for path in changed_paths for pattern in patterns
                )
            if matches:
                active.append(Layer(id=lane.id, tier=lane.tier, lanes=[lane.id]))
        return sorted(active, key=lambda layer: TIER_ORDER.index(layer.tier))

    def load_lane(self, lane_id: str) -> Lane:
        return self._by_id[lane_id].lane

    def path_for(self, lane_id: str) -> Path:
        return self._by_id[lane_id].path


def _packaged_sources() -> list[LaneSource]:
    root = files("rvw").joinpath("lanes")
    sources: list[LaneSource] = []

    def walk(resource: Traversable) -> list[Traversable]:
        if resource.is_file() and str(resource).endswith(".md"):
            return [resource]
        return [child for item in resource.iterdir() for child in walk(item)]

    for resource in sorted(walk(root), key=lambda item: str(item)):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(resource.read_text(encoding="utf-8"))
            temp_path = Path(handle.name)
        try:
            sources.append(LaneSource(load_new_lane(temp_path), Path(str(resource)), "packaged"))
        finally:
            temp_path.unlink(missing_ok=True)
    return sources


def _git_blob_files(*, cwd: Path, base_ref: str, prefix: str) -> dict[str, str]:
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", base_ref, "--", prefix],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    blobs: dict[str, str] = {}
    for name in listing.splitlines():
        if not name.endswith(".md") and not name.endswith(".yaml"):
            continue
        content = subprocess.run(
            ["git", "show", f"{base_ref}:{name}"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        blobs[name] = content
    return blobs


def _repo_sources(target: ResolvedTarget, *, cwd: Path, allow_worktree: bool) -> list[LaneSource]:
    base_ref = target.base_sha or target.head_sha
    if allow_worktree:
        paths = (
            sorted((cwd / ".rvw" / "lanes").rglob("*.md"))
            if (cwd / ".rvw" / "lanes").is_dir()
            else []
        )
        sources: list[LaneSource] = []
        for path in paths:
            lane = load_new_lane(path)
            if lane.tier is not Tier.PROJECT:
                raise ValueError(f"repository lane must use project tier: {path}")
            sources.append(LaneSource(lane, path, "worktree"))
        return sources
    blobs = _git_blob_files(cwd=cwd, base_ref=base_ref, prefix=".rvw/lanes")
    sources: list[LaneSource] = []
    for name, content in sorted(blobs.items()):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            lane = load_new_lane(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        if lane.tier is not Tier.PROJECT:
            raise ValueError(f"repository lane must use project tier: {name}")
        sources.append(LaneSource(lane, Path(name), "repo"))
    return sources


def load_effective_registry(
    target: ResolvedTarget,
    *,
    cwd: Path,
    external_root: Path | None = None,
    allow_worktree_rules: bool = False,
    activate_legacy: bool = True,
) -> EffectiveRegistry:
    """Load packaged lanes, base-ref repository lanes, and legacy fallback."""

    packaged = _packaged_sources()
    repo = _repo_sources(target, cwd=cwd, allow_worktree=allow_worktree_rules)
    legacy: list[LaneSource] = []
    root = (external_root or Path("~/.hermes/review").expanduser()).expanduser()
    layers_path = root / "layers.yaml"
    if layers_path.is_file():
        warnings.warn(
            "deprecated external review registry detected; migrate lanes to the target repo .rvw/ directory",
            UserWarning,
            stacklevel=2,
        )
        registry = load_registry(layers_path)
        active_legacy = (
            {
                lane_id
                for layer in registry.activate(target.repo, target.changed_paths)
                for lane_id in layer.lanes
            }
            if activate_legacy
            else {lane_id for layer in registry.layers for lane_id in layer.lanes}
        )
        for lane_id, tier in (
            (lane_id, layer.tier) for layer in registry.layers for lane_id in layer.lanes
        ):
            if lane_id not in active_legacy:
                continue
            path = root / "lanes" / tier.value / Path(*lane_id.split("/")).with_suffix(".md")
            if path.is_file():
                legacy.append(LaneSource(load_lane(path), path, "external"))
    # precedence is repo > external > packaged
    merged: dict[str, LaneSource] = {}
    for item in packaged + legacy + repo:
        merged[item.lane.id] = item
    return EffectiveRegistry(merged.values())


def load_repo_policy(
    target: ResolvedTarget, *, cwd: Path, allow_worktree_rules: bool = False
) -> AutoPolicy | None:
    """Load optional `.rvw/policies/auto.yaml` from the target base revision."""

    from rvw.policy import AutoPolicy

    path = cwd / ".rvw" / "policies" / "auto.yaml"
    if allow_worktree_rules:
        if not path.is_file():
            return None
        return AutoPolicy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    base_ref = target.base_sha or target.head_sha
    try:
        raw = subprocess.run(
            ["git", "show", f"{base_ref}:.rvw/policies/auto.yaml"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return AutoPolicy.model_validate(yaml.safe_load(raw))
