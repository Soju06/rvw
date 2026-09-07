"""Thin PEP 517 wrapper that embeds honest source provenance before uv_build packages rvw."""

from __future__ import annotations

import ast
import hashlib
import importlib
import re
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_PROVENANCE_MODULE = _ROOT / "src" / "rvw" / "_build_provenance.py"


def _uv_build() -> Any:
    return importlib.import_module("uv_build")


def _git(args: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _git_status_dirty() -> bool | None:
    try:
        result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "src/rvw",
                "pyproject.toml",
                "uv.lock",
            ],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def _build_id() -> str:
    digest = hashlib.sha256()
    inputs = [
        *sorted((_ROOT / "src" / "rvw").rglob("*.py")),
        _ROOT / "pyproject.toml",
        _ROOT / "uv.lock",
    ]
    for path in inputs:
        if path == _PROVENANCE_MODULE or not path.is_file():
            continue
        relative = path.relative_to(_ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _embedded_commit() -> str | None:
    """Read SOURCE_COMMIT already stamped into the provenance module, if any."""

    try:
        text = _PROVENANCE_MODULE.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^SOURCE_COMMIT: str \| None = (.+)$", text, re.MULTILINE)
    if match is None:
        return None
    try:
        value = ast.literal_eval(match.group(1).strip())
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def _generated_provenance() -> str | None:
    commit = _git(["rev-parse", "HEAD"])
    dirty = _git_status_dirty() if commit is not None else None
    if commit is None and _embedded_commit() is not None:
        # Building from an sdist that a previous backend run already stamped
        # (uv build: sdist first, then wheel from that sdist). The tree has no
        # .git here, so regenerating would erase a commit we already proved.
        return None
    built_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return (
        '"""Generated build metadata; do not edit build artifacts."""\n\n'
        f"BUILD_ID: str | None = {_build_id()!r}\n"
        f"SOURCE_COMMIT: str | None = {commit!r}\n"
        f"SOURCE_DIRTY: bool | None = {dirty!r}\n"
        f"BUILT_AT: str | None = {built_at!r}\n"
    )


@contextmanager
def _embedded_provenance() -> Iterator[None]:
    generated = _generated_provenance()
    if generated is None:
        yield
        return
    original = _PROVENANCE_MODULE.read_bytes()
    _PROVENANCE_MODULE.write_text(generated, encoding="utf-8")
    try:
        yield
    finally:
        _PROVENANCE_MODULE.write_bytes(original)


def build_wheel(
    wheel_directory: str,
    config_settings: Mapping[Any, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    with _embedded_provenance():
        return _uv_build().build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(
    wheel_directory: str,
    config_settings: Mapping[Any, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _uv_build().build_editable(wheel_directory, config_settings, metadata_directory)


def build_sdist(
    sdist_directory: str,
    config_settings: Mapping[Any, Any] | None = None,
) -> str:
    with _embedded_provenance():
        return _uv_build().build_sdist(sdist_directory, config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: Mapping[Any, Any] | None = None,
) -> str:
    return _uv_build().prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: Mapping[Any, Any] | None = None,
) -> str:
    return _uv_build().prepare_metadata_for_build_editable(metadata_directory, config_settings)


def get_requires_for_build_wheel(
    config_settings: Mapping[Any, Any] | None = None,
) -> Sequence[str]:
    return _uv_build().get_requires_for_build_wheel(config_settings)


def get_requires_for_build_editable(
    config_settings: Mapping[Any, Any] | None = None,
) -> Sequence[str]:
    return _uv_build().get_requires_for_build_editable(config_settings)


def get_requires_for_build_sdist(
    config_settings: Mapping[Any, Any] | None = None,
) -> Sequence[str]:
    return _uv_build().get_requires_for_build_sdist(config_settings)
