"""Offline contracts for the A1 container invocation."""

import json
import subprocess
from pathlib import Path

import pytest

from rvw.policy import load_policy
from rvw.runtime_policy import REASONING_EFFORT_VALUES

ROOT = Path(__file__).resolve().parents[1]


def _node_export(module: str, name: str) -> object:
    """Evaluate one export of an import-free Worker module with Node's type stripping."""
    script = f"import {{{name}}} from './{module}'; console.log(JSON.stringify({name}));"
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


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
    assert (
        "exec ${buildRvwRunInvocation({...message, deadlineSeconds, ...policy,\n"
        '  publish: policy.publication?.channels.includes("review") === false ? null : undefined})}'
    ) in source
    assert (
        "reviewScript(message, config.reviewDeadlineSeconds,\n"
        "      {model: config.codexModel, reasoningEffort: config.codexReasoningEffort,\n"
        "        publication: record.publicationPolicy})"
    ) in source
    assert "rvw.container_entrypoint run" in invocation
    assert "--deadline ${deadlineSeconds}" in invocation
    assert "--base-ref" in invocation
    assert "--head-ref" in invocation
    assert "/workspace/result" in invocation
    assert "GH_REPO=" not in invocation
    assert "rvw-auto.json" not in source
    assert "summary.markdown" in source


def test_a1_script_forwards_codex_policy_overrides_only_when_configured() -> None:
    source = (ROOT / "cloud/worker/src/review-job.ts").read_text(encoding="utf-8")
    invocation = (ROOT / "cloud/worker/src/sandbox-auth.ts").read_text(encoding="utf-8")
    config = (ROOT / "cloud/worker/src/config.ts").read_text(encoding="utf-8")

    # The flags follow --json and are rendered only for a supplied field.
    assert "` --model ${shellQuote(model)}`" in invocation
    assert "` --reasoning-effort ${shellQuote(reasoningEffort)}`" in invocation
    assert "if (model !== undefined)" in invocation
    assert "if (reasoningEffort !== undefined)" in invocation
    assert '"RVW_CODEX_MODEL"' in config
    assert '"RVW_CODEX_REASONING_EFFORT"' in config
    assert "optionalCodexModel(env.RVW_CODEX_MODEL)" in config
    assert "optionalReasoningEffort(env.RVW_CODEX_REASONING_EFFORT)" in config
    # The check text facts carry the effective values Python recorded in process.json.
    assert "runtime: mapping?.runtime ?? null" in source


def test_worker_effort_enum_matches_the_python_resolver() -> None:
    worker_values = _node_export("cloud/worker/src/sandbox-auth.ts", "REASONING_EFFORT_VALUES")
    spike_values = _node_export(
        "cloud/worker/src/spike-contract.ts", "SPIKE_REASONING_EFFORT_VALUES"
    )

    assert isinstance(worker_values, list)
    assert set(worker_values) == REASONING_EFFORT_VALUES
    assert len(worker_values) == len(REASONING_EFFORT_VALUES) == 9
    assert spike_values == worker_values


@pytest.mark.parametrize(
    ("options", "suffix"),
    [
        ({}, "--publish none --json"),
        ({"model": "gpt-6-astra"}, "--publish none --json --model 'gpt-6-astra'"),
        ({"reasoningEffort": "high"}, "--publish none --json --reasoning-effort 'high'"),
        (
            {"model": "gpt-6-astra", "reasoningEffort": "high"},
            "--publish none --json --model 'gpt-6-astra' --reasoning-effort 'high'",
        ),
    ],
)
def test_app_invocation_appends_policy_flags_after_json(
    options: dict[str, str], suffix: str
) -> None:
    script = (
        "import {buildRvwRunInvocation} from './cloud/worker/src/sandbox-auth.ts';"
        "console.log(buildRvwRunInvocation(JSON.parse(process.argv[1])));"
    )
    base = {
        "owner": "fixture",
        "repo": "project",
        "prNumber": 42,
        "baseSha": "b" * 40,
        "headSha": "a" * 40,
        "publish": "none",
        "deadlineSeconds": 900,
    }
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps({**base, **options})],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith(suffix)


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
