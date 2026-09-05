"""Execute all three adapters against real Git and offline gh/Codex fixtures."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGET = "https://github.com/fixture/project/pull/42"
TIMING_FIELDS = {"duration_ms", "wall_seconds"}


def _execute(arguments: list[str], *, cwd: Path, environ: dict[str, str]) -> str:
    result = subprocess.run(
        arguments, cwd=cwd, env=environ, capture_output=True, text=True, timeout=90, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _fixture_repo(tmp_path: Path, environ: dict[str, str]) -> tuple[Path, str, str]:
    checkout = tmp_path / "checkout with 'quote'"
    checkout.mkdir()
    _execute(["git", "init", "-b", "main"], cwd=checkout, environ=environ)
    _execute(
        ["git", "remote", "add", "origin", "https://github.com/ambient/wrong-repo.git"],
        cwd=checkout,
        environ=environ,
    )
    revisions = []
    for value in (1, 2):
        (checkout / "price.py").write_text(f"price = {value}\n")
        _execute(["git", "add", "price.py"], cwd=checkout, environ=environ)
        _execute(
            [
                "git",
                "-c",
                "user.name=Parity",
                "-c",
                "user.email=parity@example.test",
                "commit",
                "-m",
                f"price {value}",
            ],
            cwd=checkout,
            environ=environ,
        )
        revisions.append(_execute(["git", "rev-parse", "HEAD"], cwd=checkout, environ=environ))
    base, head = revisions
    target = {
        "base": base,
        "metadata": {
            "number": 42,
            "title": "Change price",
            "body": "Review the price.",
            "headRefOid": head,
            "headRefName": "price",
        },
        "diff": _execute(["git", "diff", f"{base}...{head}"], cwd=checkout, environ=environ),
    }
    Path(environ["RVW_PARITY_TARGET"]).write_text(json.dumps(target))
    return checkout, base, head


def _environment(tmp_path: Path, mode: str) -> dict[str, str]:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    source = (ROOT / "tests/fixtures/adapter_parity/fake_tools.py").read_text()
    for name in ("gh", "codex", "python"):
        executable = binaries / name
        executable.write_text(f"#!{sys.executable}\n{source}")
        executable.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    # Keep credentials and real external registries out of the subprocess fixture.
    environ = {
        key: value
        for key, value in os.environ.items()
        if not re.search(
            r"TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY|^GH_|^GITHUB_|^RVW_|^CODEX_", key
        )
    }
    environ.update(
        {
            "HOME": str(home),
            "PATH": os.pathsep.join(
                (str(binaries), str(Path(sys.executable).parent), os.environ["PATH"])
            ),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
            "RVW_HOST_CONCURRENCY": "0",
            "RVW_CODEX_SANDBOX": "danger-full-access",
            "RVW_PARITY_MODE": mode,
            "RVW_PARITY_CALLS": str(tmp_path / "calls.jsonl"),
            "RVW_PARITY_TARGET": str(tmp_path / "target.json"),
            "RVW_PARITY_TEMPLATE": str(ROOT / "docker/codex-config.toml"),
        }
    )
    return environ


def _app_command(
    *, checkout: Path, out: Path, base: str, head: str, environ: dict[str, str]
) -> str:
    # Execute the actual exported TypeScript builder, including its shell quoting.
    # Node 24 supports the repository's erasable TypeScript without npm/network.
    script = (
        "import {buildRvwRunInvocation} from './cloud/worker/src/sandbox-auth.ts';"
        "console.log(buildRvwRunInvocation(JSON.parse(process.argv[1])));"
    )
    options = {
        "owner": "fixture",
        "repo": "project",
        "prNumber": 42,
        "baseSha": base,
        "headSha": head,
        "repoDir": str(checkout),
        "out": str(out),
        "publish": "none",
    }
    return _execute(
        ["node", "--input-type=module", "-e", script, json.dumps(options)],
        cwd=ROOT,
        environ=environ,
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: 0 if key in TIMING_FIELDS else _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"rvw-\d{8}-\d{6}-\d{6}-pr-42", "rvw-TIMESTAMP-pr-42", value)
        return re.sub(
            r"UTC timestamp: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC", "UTC timestamp: TIMESTAMP", value
        )
    return value


def _snapshot(out: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    process = json.loads((out / "process.json").read_text())
    summary = json.loads((out / "summary.json").read_text())
    actual_sizes = {
        path.relative_to(out).as_posix(): path.stat().st_size
        for path in out.rglob("*")
        if path.is_file()
    }
    assert {entry["path"]: entry["size_bytes"] for entry in process["artifacts"]} == actual_sizes
    assert {"process.json", "summary.json", "run.log", "environment.txt"} <= actual_sizes.keys()
    artifacts = {}
    for name in actual_sizes:
        if name == "process.json":
            continue
        contents = (out / name).read_text()
        artifacts[name] = _normalize(json.loads(contents) if name.endswith(".json") else contents)
    process = _normalize(process)
    # First prove real byte sizes above; then compare manifest sizes after timing
    # normalization, because JSON float durations can change the actual lengths.
    normalized_sizes = {
        name: len(json.dumps(contents, ensure_ascii=False, sort_keys=True).encode())
        for name, contents in artifacts.items()
    }
    process["artifacts"] = [
        {"path": entry["path"], "size_bytes": normalized_sizes.get(entry["path"], 0)}
        for entry in process["artifacts"]
    ]
    self_entry = next(entry for entry in process["artifacts"] if entry["path"] == "process.json")
    for _ in range(10):
        normalized_size = len(json.dumps(process, ensure_ascii=False, sort_keys=True).encode())
        if self_entry["size_bytes"] == normalized_size:
            break
        self_entry["size_bytes"] = normalized_size
    else:
        pytest.fail("normalized process manifest self-size did not converge")
    return process, _normalize(summary), artifacts


@pytest.mark.parametrize(
    "status,exit_code", [("pass", 0), ("block", 1), ("invalid", 2), ("infra_failed", 3)]
)
def test_direct_container_and_app_share_execution_artifacts(
    tmp_path: Path, status: str, exit_code: int
) -> None:
    environ = _environment(tmp_path, status)
    checkout, base, head = _fixture_repo(tmp_path, environ)
    out = tmp_path / "result with 'quote'"
    anchor_base = "0" * 40 if status == "invalid" else base
    args = [
        "run",
        "--target",
        TARGET,
        "--base-ref",
        anchor_base,
        "--head-ref",
        head,
        "--out",
        str(out),
        "--repo-dir",
        str(checkout),
        "--policy",
        "auto",
        "--publish",
        "none",
        "--json",
    ]
    app_command = _app_command(
        checkout=checkout, out=out, base=anchor_base, head=head, environ=environ
    )
    container_runner = (
        "import os, sys; from pathlib import Path; "
        "from rvw.container_entrypoint import run_entrypoint; "
        "run_entrypoint(sys.argv[1:], template_path=Path(os.environ['RVW_PARITY_TEMPLATE']))"
    )
    commands = {
        "direct": [str(Path(sys.executable).parent / "rvw"), *args],
        "container": [sys.executable, "-c", container_runner, *args],
        "app": ["bash", "-c", app_command],
    }
    snapshots = {}
    calls_path = Path(environ["RVW_PARITY_CALLS"])
    for surface, command in commands.items():
        shutil.rmtree(out, ignore_errors=True)
        calls_path.unlink(missing_ok=True)
        result = subprocess.run(
            command,
            cwd=checkout,
            env=environ,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == exit_code, f"{surface}: {result.stdout}\n{result.stderr}"
        process, summary, artifacts = _snapshot(out)
        assert process["status"] == status
        assert process["exit_code"] == exit_code
        assert process["target"] == {
            "repo": "fixture/project",
            "pr": 42,
            "base": base,
            "head": head,
        }
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
        github_calls = [call["argv"] for call in calls if call["tool"] == "gh"]
        assert len(github_calls) == 4
        assert all(
            "--repo" in argv or argv[:2] == ["api", "repos/fixture/project/pulls/42"]
            for argv in github_calls
        )
        runtime_calls = [
            call for call in calls if call["tool"] == "codex" and call["argv"][0] == "exec"
        ]
        if status == "invalid":
            assert process["failure"]["code"] == "target_anchor_mismatch"
            assert not runtime_calls
        else:
            assert runtime_calls
            assert process["effective_policy"] == {
                "source": "package",
                "path": "rvw:resources/policies/auto-default.yaml",
            }
            assert summary["lanes"]["dispatched"] > 0
            if status == "infra_failed":
                assert process["failure"]["code"] == "review_failed"
                assert summary["lanes"]["valid"] == 0
            else:
                assert summary["lanes"]["valid"] == summary["lanes"]["dispatched"]
                assert summary["lanes"]["uncovered"] == 0
                assert bool(summary["blockers"]) == (status == "block")
        snapshots[surface] = (process, summary, artifacts)
    expected_process, expected_summary, expected_artifacts = snapshots["direct"]
    for surface in ("container", "app"):
        process, summary, artifacts = snapshots[surface]
        assert process == expected_process, f"{surface} process contract differs"
        assert summary == expected_summary, f"{surface} summary contract differs"
        assert artifacts.keys() == expected_artifacts.keys(), f"{surface} artifact layout differs"
        for name, contents in artifacts.items():
            assert contents == expected_artifacts[name], f"{surface} artifact {name} differs"
    assert (Path(environ["HOME"]) / ".codex/config.toml").read_text() == (
        ROOT / "docker/codex-config.toml"
    ).read_text()
