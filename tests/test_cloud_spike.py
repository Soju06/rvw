"""Regression contracts for the bounded Cloudflare A0 spike path."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_spike_driver_accepts_target_and_configurable_deadline() -> None:
    driver = (ROOT / "cloud/scripts/drive-spike.sh").read_text(encoding="utf-8")

    assert "[[ $# -lt 3 || $# -gt 4 ]]" in driver
    assert "repo=$repo_url&target=$target_sha" in driver
    assert "target_sha=$3" in driver
    assert "deadline_seconds=${4:-1500}" in driver
    assert "target=$target_sha" in driver
    assert "observer outcome is not evidence that the review failed" in driver
    assert "transport/API failure" in driver
    assert "review completed with non-zero process exit code" in driver
    assert "exit 6" in driver


def test_worker_validates_target_and_reads_process_result_artifacts() -> None:
    routes = (ROOT / "cloud/worker/src/routes.ts").read_text(encoding="utf-8")
    contract = (ROOT / "cloud/worker/src/spike-contract.ts").read_text(encoding="utf-8")

    assert 'required(url, "repo")' in routes
    assert 'required(url, "target")' in routes
    assert "/^[0-9a-f]{7,40}$/" in contract
    assert "`/workspace/result/${name}`" in contract
    assert "CODEX_BASE_URL: `https://${proxyHost}/backend-api/codex`" in contract
    assert "RVW_CODEX_SANDBOX" not in contract
    assert "env RVW_CODEX_SANDBOX=read-only codex exec" in routes
    assert "env RVW_CODEX_SANDBOX=danger-full-access python -m rvw.container_entrypoint" in routes
    assert "unset RVW_CODEX_DEFAULT_BASE_URL RVW_CODEX_SANDBOX" in routes


def test_cloud_codex_template_leaves_runtime_base_url_unconfigured() -> None:
    template = (ROOT / "cloud/docker/codex-config.toml").read_text(encoding="utf-8")

    assert "base_url" not in template


def test_egress_injection_emits_secret_free_structured_event() -> None:
    sandbox = (ROOT / "cloud/worker/src/sandbox.ts").read_text(encoding="utf-8")
    sandbox_config = (ROOT / "cloud/worker/src/sandbox-config.ts").read_text(encoding="utf-8")

    assert 'event: "codex_credential_injected"' in sandbox_config
    assert "JSON.stringify" in sandbox_config
    assert "interceptHttps = true" in sandbox
