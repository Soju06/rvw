"""Contracts for the container image and its startup configuration."""

from __future__ import annotations

import re
import stat
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


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


def test_entrypoint_forwards_the_app_deadline_verbatim(tmp_path: Path) -> None:
    from rvw.container_entrypoint import run_entrypoint

    observed: list[list[str]] = []
    argv = [
        "run",
        "--target",
        "https://github.com/acme/rockets/pull/42",
        "--base-ref",
        "b" * 40,
        "--head-ref",
        "a" * 40,
        "--out",
        "/workspace/result",
        "--deadline",
        "900",
        "--policy",
        "auto",
        "--publish",
        "github-review",
        "--json",
    ]
    run_entrypoint(
        argv,
        template_path=_template(),
        environ={"HOME": str(tmp_path)},
        execvp=lambda _executable, forwarded: observed.append(list(forwarded)),
    )

    assert observed == [["rvw", *argv]]
    assert observed[0][observed[0].index("--deadline") + 1] == "900"


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


@pytest.mark.parametrize("name", ["Dockerfile", "cloud/Dockerfile"])
def test_both_images_install_review_phase_shims_ahead_of_the_real_binaries(name: str) -> None:
    dockerfile = (ROOT / name).read_text(encoding="utf-8")
    normalized = dockerfile.replace("\\\n", " ")

    assert "COPY docker/shims/ /opt/rvw-shims/" in dockerfile
    assert "COPY docker/rvw-shims.sh /etc/profile.d/rvw-shims.sh" in dockerfile
    assert (
        "COPY docker/check-review-shims.sh /usr/local/lib/rvw/check-review-shims.sh" in dockerfile
    )
    assert "bash /usr/local/lib/rvw/check-review-shims.sh" in normalized
    path_values = re.findall(r'PATH="([^"]+)"', dockerfile)
    assert path_values, "expected an ENV PATH assignment"
    assert all(value.startswith("/opt/rvw-shims:") for value in path_values)
    # The shims narrow tool commands; the measured sandbox fallback itself is unchanged.
    assert "RVW_CODEX_SANDBOX=danger-full-access" in dockerfile
    for tool in ("git", "gh", "curl", "wget"):
        assert (ROOT / "docker" / "shims" / tool).stat().st_mode & stat.S_IXUSR
    assert (ROOT / "docker" / "shims" / "rvw-shim-lib.sh").is_file()


def test_docker_context_excludes_credentials_and_runtime_artifacts() -> None:
    exclusions = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for entry in (".git", ".env", ".codex", ".hermes", ".venv", "auth.json"):
        assert entry in exclusions


def test_both_images_copy_one_codex_configuration_template() -> None:
    for name in ("Dockerfile", "cloud/Dockerfile"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "COPY docker/codex-config.toml /etc/rvw/codex-config.toml" in source
    assert not (ROOT / "cloud/docker/codex-config.toml").exists()


def test_review_workflow_surface_is_retired() -> None:
    workflows = sorted(path for pattern in ("*.yml", "*.yaml") for path in WORKFLOWS.glob(pattern))
    assert not any(path.stem == "rvw-review" for path in workflows)
    reusable = sorted(
        path.name for path in workflows if "workflow_call:" in path.read_text(encoding="utf-8")
    )
    # Deliberate tripwire: only the Worker CD contract may be a reusable workflow. A new
    # workflow_call workflow must be reviewed here so a review surface cannot return quietly.
    assert reusable == ["rvw-deploy.yml"]
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert "rvw-review.yml" not in codeowners
    assert "container-ci.md" not in codeowners


def test_container_image_docs_show_direct_run_and_immutable_pins() -> None:
    docs = (ROOT / "docs/container-image.md").read_text(encoding="utf-8")
    normalized_docs = " ".join(docs.split())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not (ROOT / "docs/container-ci.md").exists()
    assert "ghcr.io/soju06/rvw:vX.Y.Z" in docs
    assert "ghcr.io/soju06/rvw:latest" in docs
    assert "mutable convenience tag" in normalized_docs
    assert "ghcr.io/soju06/rvw@sha256:" in docs
    assert "publish-image" in docs
    assert "RVW_IMAGE_VERSION=X.Y.Z" in docs
    assert "CODEX_BASE_URL=" in docs
    assert "package visibility checklist" in normalized_docs
    assert "Public" in docs
    run_block = next(block for block in docs.split("```")[1::2] if "run --target" in block)
    assert "ghcr.io/soju06/rvw:vX.Y.Z" in run_block
    assert "rvw:latest" not in run_block
    for hardening in (
        "--read-only",
        "--tmpfs /root",
        '--volume "$PWD:/workspace:ro"',
        "GIT_CONFIG_KEY_0=safe.directory",
        "GIT_CONFIG_VALUE_0=/workspace",
        "--out /result",
    ):
        assert hardening in run_block
    assert "checkout-verification-failed" in docs
    assert "cloud/README.md" in docs
    for retired in ("rvw-review.yml", "rvw-review.yaml", "workflows/rvw.yml", "uses: <your-org>"):
        assert retired not in docs
    assert "automatically publishes" in readme
    assert "version tag or digest" in readme
    assert "GitHub App" in readme
    assert "docs/container-image.md" in readme
    assert "container-ci.md" not in readme
