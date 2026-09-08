"""Offline contracts for the A1 container invocation."""

import json
from pathlib import Path

import pytest

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
    assert "exec ${buildRvwRunInvocation({...message, deadlineSeconds})}" in source
    assert "reviewScript(message, config.reviewDeadlineSeconds)" in source
    assert "rvw.container_entrypoint run" in invocation
    assert "--deadline ${deadlineSeconds}" in invocation
    assert "--base-ref" in invocation
    assert "--head-ref" in invocation
    assert "/workspace/result" in invocation
    assert "GH_REPO=" not in invocation
    assert "rvw-auto.json" not in source
    assert "summary.markdown" in source


def _wrangler_vars() -> dict[str, dict[str, str]]:
    config = json.loads((ROOT / "cloud/wrangler.jsonc").read_text(encoding="utf-8"))
    return {"dev": config["vars"], **{name: env["vars"] for name, env in config["env"].items()}}


@pytest.mark.parametrize("environment", ["dev", "spike", "prod"])
def test_committed_job_deadline_covers_the_explicit_review_budget(environment: str) -> None:
    variables = _wrangler_vars()[environment]
    review_seconds = int(variables["RVW_REVIEW_DEADLINE_SECONDS"])
    job_minutes = int(variables["RVW_JOB_DEADLINE_MINUTES"])

    assert 1 <= review_seconds <= 1800  # the CLI --deadline ceiling
    # Five runtime waves on the no-adjudication-retry path plus ten minutes of slack.
    assert job_minutes * 60 >= 5 * review_seconds + 600


def test_review_deadline_is_a_var_shared_by_every_environment() -> None:
    variables = _wrangler_vars()
    assert {env["RVW_REVIEW_DEADLINE_SECONDS"] for env in variables.values()} == {"900"}
    assert {env["RVW_JOB_DEADLINE_MINUTES"] for env in variables.values()} == {"120"}
