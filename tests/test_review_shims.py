"""Bash fixture tests for the review-phase PATH shims shipped in the container images."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHIMS = ROOT / "docker" / "shims"
PROFILE_HOOK = ROOT / "docker" / "rvw-shims.sh"
SELF_TEST = ROOT / "docker" / "check-review-shims.sh"
TOOLS = ("git", "gh", "curl", "wget")
GIT_REFUSAL = "rvw: remote git is disabled during review"

FAKE_REAL_BINARY = """#!/usr/bin/env bash
printf 'REAL %s' "$(basename "$0")"
for arg in "$@"; do printf ' [%s]' "$arg"; done
printf '\\n'
"""


@pytest.fixture
def real_bin(tmp_path: Path) -> Path:
    """A directory of fake real binaries that echo their argv, placed after the shims."""

    directory = tmp_path / "real"
    directory.mkdir()
    for tool in TOOLS:
        target = directory / tool
        target.write_text(FAKE_REAL_BINARY, encoding="utf-8")
        target.chmod(0o755)
    return directory


def run_shim(
    tool: str,
    *args: str,
    real_bin: Path,
    phase: str | None,
    shim_dir: Path = SHIMS,
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": f"{shim_dir}:{real_bin}:/usr/bin:/bin", "HOME": "/tmp"}
    if phase is not None:
        env["RVW_PHASE"] = phase
    return subprocess.run(
        [str(shim_dir / tool), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_shim_scripts_are_executable_bash_and_pass_syntax_checks() -> None:
    for tool in TOOLS:
        path = SHIMS / tool
        assert path.stat().st_mode & stat.S_IXUSR, f"{tool} shim must be executable"
        assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash\n")
    for script in (*(SHIMS / tool for tool in TOOLS), SHIMS / "rvw-shim-lib.sh", SELF_TEST):
        subprocess.run(["bash", "-n", str(script)], check=True)
    subprocess.run(["sh", "-n", str(PROFILE_HOOK)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_shim_scripts_pass_shellcheck() -> None:
    subprocess.run(
        ["shellcheck", "-x", "-P", "SCRIPTDIR", *TOOLS, "rvw-shim-lib.sh"],
        cwd=SHIMS,
        check=True,
    )
    subprocess.run(["shellcheck", str(SELF_TEST)], check=True)
    subprocess.run(["shellcheck", "-s", "sh", str(PROFILE_HOOK)], check=True)


@pytest.mark.parametrize(
    "argv",
    [
        ["fetch", "origin", "main"],
        ["-C", "/tmp", "-c", "core.pager=cat", "pull"],
        ["--git-dir=/tmp/x", "fetch"],
        ["clone", "https://example.invalid/example.git"],
        ["ls-remote", "origin"],
        ["push", "origin", "HEAD"],
        ["remote", "add", "upstream", "https://example.invalid/example.git"],
        ["remote", "set-url", "origin", "ssh://example.invalid/example.git"],
        ["submodule", "update", "--init"],
        ["archive", "--remote=origin", "HEAD"],
        ["log", "https://example.invalid/example.git"],
        ["ls-remote", "git@example.invalid:example/example.git"],
        ["fetch-pack", "example.invalid"],
    ],
)
def test_git_shim_refuses_remote_access_during_review(real_bin: Path, argv: list[str]) -> None:
    result = run_shim("git", *argv, real_bin=real_bin, phase="review")

    assert result.returncode == 2
    assert result.stderr == f"{GIT_REFUSAL}\n"
    assert result.stdout == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--short"],
        ["-C", "/tmp", "-c", "core.pager=cat", "status", "--short"],
        ["diff", "--stat", "abc...def", "--", "path with spaces.py"],
        ["show", "HEAD"],
        ["log", "--oneline", "-1"],
        ["rev-parse", "HEAD"],
        ["remote", "-v"],
        ["remote", "get-url", "origin"],
        ["submodule", "status"],
        ["archive", "HEAD"],
    ],
)
def test_git_shim_passes_local_commands_through_verbatim_during_review(
    real_bin: Path, argv: list[str]
) -> None:
    result = run_shim("git", *argv, real_bin=real_bin, phase="review")

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "REAL git" + "".join(f" [{arg}]" for arg in argv) + "\n"


@pytest.mark.parametrize("phase", [None, "checkout", "publication"])
@pytest.mark.parametrize(
    ("tool", "argv"),
    [
        ("git", ["fetch", "--no-tags", "origin", "refs/pull/1/head"]),
        ("git", ["clone", "https://example.invalid/example.git", "dest"]),
        ("gh", ["repo", "clone", "owner/repo", "dest", "--", "--no-checkout"]),
        ("gh", ["api", "repos/owner/repo/pulls/1", "--jq", ".base.sha"]),
        ("curl", ["-sS", "https://example.invalid/"]),
        ("wget", ["-q", "https://example.invalid/"]),
    ],
)
def test_shims_are_transparent_outside_the_review_phase(
    real_bin: Path, phase: str | None, tool: str, argv: list[str]
) -> None:
    result = run_shim(tool, *argv, real_bin=real_bin, phase=phase)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == f"REAL {tool}" + "".join(f" [{arg}]" for arg in argv) + "\n"


@pytest.mark.parametrize(
    ("tool", "argv"),
    [
        ("gh", ["api", "repos/owner/repo"]),
        ("gh", ["pr", "view", "1", "--repo", "owner/repo"]),
        ("gh", ["repo", "clone", "owner/repo"]),
        ("curl", ["-sS", "https://example.invalid/"]),
        ("curl", ["-L", "-o", "/tmp/out", "http://example.invalid/"]),
        ("wget", ["-q", "https://example.invalid/"]),
    ],
)
def test_network_tool_shims_refuse_everything_during_review(
    real_bin: Path, tool: str, argv: list[str]
) -> None:
    result = run_shim(tool, *argv, real_bin=real_bin, phase="review")

    assert result.returncode == 2
    assert result.stderr == f"rvw: {tool} is disabled during review\n"
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("tool", "argv"),
    [("gh", ["--version"]), ("gh", ["help"]), ("curl", ["--version"]), ("wget", ["--version"])],
)
def test_network_tool_shims_allow_version_and_help_during_review(
    real_bin: Path, tool: str, argv: list[str]
) -> None:
    result = run_shim(tool, *argv, real_bin=real_bin, phase="review")

    assert result.returncode == 0
    assert result.stdout == f"REAL {tool}" + "".join(f" [{arg}]" for arg in argv) + "\n"


def test_shim_resolves_the_real_binary_by_skipping_its_own_directory(
    tmp_path: Path, real_bin: Path
) -> None:
    # A symlinked copy of the shim directory must still skip itself when resolving.
    linked = tmp_path / "linked-shims"
    linked.symlink_to(SHIMS, target_is_directory=True)

    result = run_shim("git", "status", real_bin=real_bin, phase="review", shim_dir=linked)

    assert result.returncode == 0
    assert result.stdout == "REAL git [status]\n"


def test_shim_fails_closed_when_the_real_binary_is_missing(tmp_path: Path) -> None:
    # Only the coreutils the shim itself needs are reachable; no git exists anywhere on PATH.
    utilities = tmp_path / "utilities"
    utilities.mkdir()
    for name in ("bash", "dirname", "basename"):
        (utilities / name).symlink_to(shutil.which(name) or f"/usr/bin/{name}")

    result = subprocess.run(
        [str(SHIMS / "git"), "status"],
        env={"PATH": f"{SHIMS}:{utilities}", "HOME": "/tmp", "RVW_PHASE": "checkout"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 127
    assert result.stderr == "rvw: git is not installed\n"


def test_profile_hook_prepends_the_shim_directory_once() -> None:
    script = f". {PROFILE_HOOK}; . {PROFILE_HOOK}; printf '%s' \"$PATH\""
    result = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == "/opt/rvw-shims:/usr/bin:/bin"


def test_git_shim_is_not_tricked_by_option_values_named_like_remote_subcommands(
    real_bin: Path,
) -> None:
    result = run_shim(
        "git", "-C", "fetch", "-c", "alias.f=fetch", "status", real_bin=real_bin, phase="review"
    )

    assert result.returncode == 0
    assert result.stdout == "REAL git [-C] [fetch] [-c] [alias.f=fetch] [status]\n"


def test_runtime_environment_marks_the_review_phase_for_the_shims() -> None:
    from rvw.runtimes.codex import REVIEW_PHASE_ENVIRONMENT, review_phase_environment

    environment = review_phase_environment({"PATH": "/opt/rvw-shims:/usr/bin", "HOME": "/root"})

    assert environment["RVW_PHASE"] == "review"
    assert environment["GIT_ALLOW_PROTOCOL"] == "none"
    assert environment["PATH"] == "/opt/rvw-shims:/usr/bin"
    assert dict(REVIEW_PHASE_ENVIRONMENT) == {"RVW_PHASE": "review", "GIT_ALLOW_PROTOCOL": "none"}
    assert os.environ.get("RVW_PHASE") != "review"
