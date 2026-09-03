"""Contracts for the container image, startup config, and reusable CI entry."""

from __future__ import annotations

import stat
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

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
        ["auto", "--target", "deadbeef", "--repo-dir", "/workspace"],
        template_path=_template(),
        environ=environ,
        execvp=fake_execvp,
    )

    assert observed == [
        ("rvw", ["rvw", "auto", "--target", "deadbeef", "--repo-dir", "/workspace"])
    ]


def test_dockerfile_pins_complete_multistage_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM ") >= 3
    assert "python:3.12-slim-bookworm" in dockerfile
    assert "node:24-bookworm-slim" in dockerfile
    assert "ghcr.io/astral-sh/uv:" in dockerfile
    assert "@openai/codex@0.152.0" in dockerfile
    for package in ("bash", "coreutils", "git", "gh", "ripgrep", "util-linux"):
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


def test_reusable_workflow_pins_base_side_checkout_and_auto_exit_contract() -> None:
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
    assert "PR_NUMBER: ${{ github.event.pull_request.number }}" in workflow
    assert "git fetch" in workflow
    assert "CODEX_API_KEY: ${{ secrets.CODEX_API_KEY }}" in workflow
    assert "CODEX_BASE_URL:" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "--workdir /workspace" in workflow
    assert ":/workspace:ro" in workflow
    assert 'auto --target "$PR_NUMBER" --repo-dir /workspace' in workflow
    assert "continue-on-error" not in workflow


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
