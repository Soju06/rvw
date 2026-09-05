"""Contracts for the container image, startup config, and reusable CI entry."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _template() -> Path:
    return ROOT / "docker/codex-config.toml"


def test_config_materialization_prefers_runtime_url_and_never_writes_secret(
    tmp_path: Path,
) -> None:
    from rvw.container_entrypoint import materialize_codex_config

    secret = "not-a-real-secret"
    config_path = materialize_codex_config(
        template_path=_template(),
        home=tmp_path,
        environ={
            "CODEX_API_KEY": secret,
            "CODEX_BASE_URL": 'https://runtime.example/v1?q="quoted"',
            "RVW_CODEX_DEFAULT_BASE_URL": "https://build.example/v1",
        },
    )

    config_text = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    provider = config["model_providers"]["rvw"]
    assert config["model_provider"] == "rvw"
    assert provider["env_key"] == "CODEX_API_KEY"
    assert provider["base_url"] == 'https://runtime.example/v1?q="quoted"'
    assert secret not in config_text
    assert not (tmp_path / ".codex/auth.json").exists()
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700


def test_config_materialization_uses_build_default_without_runtime_url(tmp_path: Path) -> None:
    from rvw.container_entrypoint import materialize_codex_config

    config_path = materialize_codex_config(
        template_path=_template(),
        home=tmp_path,
        environ={"RVW_CODEX_DEFAULT_BASE_URL": "https://build.example/v1"},
    )

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["model_providers"]["rvw"]["base_url"] == "https://build.example/v1"


def test_config_materialization_keeps_missing_url_unconfigured(tmp_path: Path) -> None:
    from rvw.container_entrypoint import materialize_codex_config

    config_path = materialize_codex_config(template_path=_template(), home=tmp_path, environ={})

    config_text = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    assert "base_url" not in config["model_providers"]["rvw"]
    assert "nekos" not in config_text.casefold()
    assert not (tmp_path / ".codex/auth.json").exists()


def test_entrypoint_preserves_rvw_arguments(tmp_path: Path) -> None:
    from rvw.container_entrypoint import run_entrypoint

    observed: list[tuple[str, list[str]]] = []

    def fake_execvp(executable: str, argv: Sequence[str]) -> None:
        observed.append((executable, list(argv)))

    environ: Mapping[str, str] = {"HOME": str(tmp_path)}
    run_entrypoint(
        ["run", "--target", "deadbeef", "--repo-dir", "/workspace"],
        template_path=_template(),
        environ=environ,
        execvp=fake_execvp,
    )

    assert observed == [("rvw", ["rvw", "run", "--target", "deadbeef", "--repo-dir", "/workspace"])]


def test_dockerfile_pins_complete_multistage_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM ") >= 3
    assert "python:3.12-slim-bookworm" in dockerfile
    assert "node:24-bookworm-slim" in dockerfile
    assert "ghcr.io/astral-sh/uv:" in dockerfile
    assert "@openai/codex@0.152.0" in dockerfile
    for package in ("bash", "coreutils", "git", "ripgrep", "util-linux"):
        assert package in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "COPY src" in dockerfile
    assert 'ARG CODEX_BASE_URL=""' in dockerfile
    assert "RVW_CODEX_DEFAULT_BASE_URL" in dockerfile
    assert "RVW_CODEX_SANDBOX=danger-full-access" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "rvw.container_entrypoint"]' in dockerfile
    assert "CODEX_API_KEY=" not in dockerfile
    assert "auth.json" not in dockerfile
    assert "codex.nekos.me" not in dockerfile


def test_docker_context_excludes_credentials_and_runtime_artifacts() -> None:
    exclusions = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for entry in (".git", ".env", ".codex", ".hermes", ".venv", "auth.json"):
        assert entry in exclusions


def test_reusable_workflow_pins_base_side_checkout_and_run_exit_contract() -> None:
    workflow = (ROOT / ".github/workflows/rvw-review.yml").read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "image:" in workflow
    assert "required: true" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: write" in workflow
    assert "persist-credentials: false" in workflow
    assert "github.event.pull_request.head.repo.full_name" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "PR_URL: ${{ github.event.pull_request.html_url }}" in workflow
    assert "git fetch" in workflow
    assert "CODEX_API_KEY: ${{ secrets.CODEX_API_KEY }}" in workflow
    assert "CODEX_BASE_URL:" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "--workdir /workspace" in workflow
    assert ":/workspace:ro" in workflow
    assert 'run --target "$PR_URL"' in workflow
    assert '--base-ref "$BASE_SHA" --head-ref "$HEAD_SHA"' in workflow
    assert "--repo-dir /workspace --out /result" in workflow
    assert '--policy auto --publish "$PUBLISH"' in workflow
    assert '--volume "$GITHUB_WORKSPACE/result:/result:rw"' in workflow
    assert "timeout-minutes: ${{ inputs.timeout_minutes }}" in workflow
    assert "default: 90" in workflow
    assert "if: always()" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "process.json" in workflow
    assert "summary.json" in workflow
    assert "continue-on-error" not in workflow


def test_both_images_copy_one_codex_configuration_template() -> None:
    for name in ("Dockerfile", "cloud/Dockerfile"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "COPY docker/codex-config.toml /etc/rvw/codex-config.toml" in source
    assert not (ROOT / "cloud/docker/codex-config.toml").exists()


@pytest.mark.parametrize(
    ("exit_code", "status", "pull_failure"),
    [
        (0, "pass", False),
        (1, "block", False),
        (2, "invalid", False),
        (3, "infra_failed", False),
        (125, None, False),
        (1, None, True),
    ],
)
def test_actions_adapter_propagates_exit_and_renders_contract(
    tmp_path: Path, exit_code: int, status: str | None, pull_failure: bool
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/rvw-review.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["review"]["steps"]}
    fixture = {"schema_version": 1, "status": status, "exit_code": exit_code}
    if exit_code in (2, 3):
        fixture["failure"] = {"code": "fixture_failure", "detail": "canonical detail"}
    (tmp_path / "fixture.json").write_text(json.dumps(fixture))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1] == 'pull':\n"
        "    sys.exit(int(os.environ['PULL_EXIT_CODE']))\n"
        "root = Path(os.environ['GITHUB_WORKSPACE'])\n"
        "(root / 'argv.json').write_text(json.dumps(sys.argv[1:]))\n"
        "fixture = json.loads((root / 'fixture.json').read_text())\n"
        "if fixture['status'] is not None:\n"
        "    (root / 'result/process.json').write_text(json.dumps(fixture))\n"
        "    (root / 'result/summary.json').write_text(json.dumps({'schema_version': 1, 'markdown': 'Shared facts: 3 valid lanes.'}))\n"
        "print('PASS: deliberately misleading stdout')\n"
        "sys.exit(fixture['exit_code'])\n"
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "step-output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary"),
        "RVW_IMAGE": "rvw-fixture:fixed",
        "PR_URL": "https://github.com/base-owner/project/pull/42",
        "BASE_SHA": "a" * 40,
        "HEAD_SHA": "b" * 40,
        "PUBLISH": "none",
        "REPLICAS": "1",
        "ADJUDICATE_REPLICAS": "3",
        "CONCURRENCY": "8",
        "DEADLINE": "600",
        "DISCOVERY_MODE": "inline",
        "PULL_EXIT_CODE": "1" if pull_failure else "0",
    }
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            steps["Run pinned rvw image"]["run"],
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    expected_exit = exit_code if exit_code in (0, 1, 2, 3) and not pull_failure else 3
    assert result.returncode == expected_exit
    assert (tmp_path / "step-output").read_text() == f"exit_code={expected_exit}\n"
    if pull_failure:
        assert not (tmp_path / "argv.json").exists()
    else:
        argv = json.loads((tmp_path / "argv.json").read_text())
        image_index = argv.index("rvw-fixture:fixed")
        assert argv[image_index + 1 : image_index + 4] == ["run", "--target", env["PR_URL"]]
        for option, value in (
            ("--base-ref", env["BASE_SHA"]),
            ("--head-ref", env["HEAD_SHA"]),
            ("--repo-dir", "/workspace"),
            ("--out", "/result"),
            ("--publish", "none"),
        ):
            assert argv[argv.index(option) + 1] == value
        assert f"{tmp_path}/result:/result:rw" in argv

    summary_result = subprocess.run(
        ["bash", "-e", "-c", steps["Render canonical review summary"]["run"]],
        env={**env, "REVIEW_EXIT_CODE": str(expected_exit)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert summary_result.returncode == (3 if status is None else 0), summary_result.stderr
    rendered = (tmp_path / "step-summary").read_text()
    if status is None:
        assert "Infrastructure failure: process.json unavailable or invalid (exit 3)" in rendered
    else:
        assert f"Status: **{status}** (exit {exit_code})" in rendered
        assert "Shared facts: 3 valid lanes." in rendered
        if exit_code in (2, 3):
            assert "fixture_failure" in rendered
            assert "canonical detail" in rendered


@pytest.mark.parametrize(
    ("process_json", "summary_json"),
    [
        (None, {"schema_version": 1, "markdown": "Fixture facts"}),
        ([], {"schema_version": 1, "markdown": "Fixture facts"}),
        (
            {"schema_version": 2, "status": "pass", "exit_code": 0},
            {"schema_version": 1, "markdown": "Fixture facts"},
        ),
        (
            {"schema_version": 1, "status": "block", "exit_code": 0},
            {"schema_version": 1, "markdown": "Fixture facts"},
        ),
        (
            {"schema_version": 1, "status": "block", "exit_code": 1},
            {"schema_version": 1, "markdown": "Fixture facts"},
        ),
        ({"schema_version": 1, "status": "pass", "exit_code": 0}, None),
        (
            {"schema_version": 1, "status": "pass", "exit_code": 0},
            {"schema_version": 2, "markdown": "Fixture facts"},
        ),
        (
            {"schema_version": 1, "status": "pass", "exit_code": 0},
            {"schema_version": 1, "markdown": []},
        ),
    ],
)
def test_actions_cannot_pass_with_missing_or_inconsistent_contract(
    tmp_path: Path, process_json: object, summary_json: object
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/rvw-review.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["review"]["steps"]}
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    for filename, value in (("process.json", process_json), ("summary.json", summary_json)):
        if value is not None:
            (result_dir / filename).write_text(json.dumps(value))
    result = subprocess.run(
        ["bash", "-e", "-c", steps["Render canonical review summary"]["run"]],
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary"),
            "REVIEW_EXIT_CODE": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3, result.stderr
    assert "Infrastructure failure:" in (tmp_path / "step-summary").read_text()
    assert steps["Retain review artifacts"]["if"] == "always()"


def test_container_ci_docs_include_exact_base_controlled_caller() -> None:
    docs = (ROOT / "docs/container-ci.md").read_text(encoding="utf-8")
    normalized_docs = " ".join(docs.split())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "pull_request_target:" in docs
    assert "<your-org>/<your-fork>/.github/workflows/rvw-review.yml@v0.4.1" in docs
    assert "ghcr.io/soju06/rvw:v0.4.1" in docs
    assert "ghcr.io/soju06/rvw:latest" in docs
    assert "ghcr.io/soju06/rvw@sha256:" in docs
    assert "publish-image" in docs
    assert "RVW_IMAGE_VERSION=0.4.1" in docs
    assert "CODEX_BASE_URL=" in docs
    assert "package visibility checklist" in normalized_docs
    assert "Public" in docs
    assert ".rvw/**" in docs
    assert ".github/workflows/rvw.yml" in docs
    assert "base-side workflow definition" in docs
    assert "not configured as a required check" in docs
    assert "automatically publishes" in readme
    assert "version tag or digest" in readme
