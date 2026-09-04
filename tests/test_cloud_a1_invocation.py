"""Offline contracts for the A1 container invocation."""

from pathlib import Path

from rvw.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


def test_cloud_image_installs_versioned_fallback_auto_policy() -> None:
    dockerfile = (ROOT / "cloud/Dockerfile").read_text(encoding="utf-8")
    policy = ROOT / "cloud/docker/auto-policy.yaml"

    assert policy.is_file()
    assert load_policy(policy).publish_state == "comment"
    assert (
        "COPY cloud/docker/auto-policy.yaml /root/.hermes/review/policies/auto.yaml" in dockerfile
    )


def test_a1_script_preserves_stderr_and_writes_redacted_environment() -> None:
    source = (ROOT / "cloud/worker/src/review-job.ts").read_text(encoding="utf-8")

    assert "autoCleanup: false" in source
    assert '2> >(tee -a "$RESULT/run.log" >&2)' in source
    assert "'/(bearer|token|key=)/I" in source
    assert '"$RESULT/environment.txt"' in source
