"""Offline contracts for the A1 container invocation."""

from pathlib import Path

from rvw.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


def test_images_get_fallback_auto_policy_from_package() -> None:
    dockerfile = (ROOT / "cloud/Dockerfile").read_text(encoding="utf-8")
    policy = ROOT / "src/rvw/resources/policies/auto-default.yaml"

    assert policy.is_file()
    assert load_policy(policy).publish_state == "comment"
    assert "cloud/docker/auto-policy.yaml" not in dockerfile
    assert "/root/.hermes/review/policies" not in dockerfile
    assert not (ROOT / "cloud/docker/auto-policy.yaml").exists()


def test_a1_script_delegates_execution_and_diagnostics_to_run() -> None:
    source = (ROOT / "cloud/worker/src/review-job.ts").read_text(encoding="utf-8")
    invocation = (ROOT / "cloud/worker/src/sandbox-auth.ts").read_text(encoding="utf-8")

    assert "autoCleanup: false" in source
    assert "exec ${buildRvwRunInvocation(message)}" in source
    assert "rvw.container_entrypoint run" in invocation
    assert "--base-ref" in invocation
    assert "--head-ref" in invocation
    assert "/workspace/result" in invocation
    assert "GH_REPO=" not in invocation
    assert "rvw-auto.json" not in source
    assert "summary.markdown" in source
