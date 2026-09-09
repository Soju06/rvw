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


def test_spike_driver_forwards_codex_overrides_from_its_environment() -> None:
    driver = (ROOT / "cloud/scripts/drive-spike.sh").read_text(encoding="utf-8")

    # Set-ness, not emptiness, decides forwarding so the Worker can reject a blank value.
    assert '[[ -n "${RVW_CODEX_MODEL+set}" ]]' in driver
    assert '[[ -n "${RVW_CODEX_REASONING_EFFORT+set}" ]]' in driver
    assert 'override_args+=(--arg model "$RVW_CODEX_MODEL")' in driver
    assert 'override_args+=(--arg reasoning_effort "$RVW_CODEX_REASONING_EFFORT")' in driver
    assert """jq -n "${override_args[@]}" '$ARGS.named'""" in driver
    assert "--header 'Content-Type: application/json' --data \"$start_body\"" in driver
    # Guarded expansion: an empty array under ``set -u`` is an error on bash 3.2 (macOS).
    assert '${start_body_args[@]+"${start_body_args[@]}"}' in driver
    # repo/target stay query parameters; the body only carries the overrides.
    assert '--request POST "$base_url/start?repo=$repo_url&target=$target_sha"' in driver


def test_worker_validates_target_and_reads_process_result_artifacts() -> None:
    routes = (ROOT / "cloud/worker/src/routes.ts").read_text(encoding="utf-8")
    contract = (ROOT / "cloud/worker/src/spike-contract.ts").read_text(encoding="utf-8")

    assert 'required(url, "repo")' in routes
    assert 'required(url, "target")' in routes
    assert "/^[0-9a-f]{7,40}$/" in contract
    assert "artifactManifest" in routes
    assert "artifactPath" in routes
    assert "CODEX_BASE_URL: `https://${proxyHost}/backend-api/codex`" in contract
    assert "RVW_CODEX_SANDBOX" not in contract
    assert "env RVW_CODEX_SANDBOX=read-only codex exec" in routes
    assert "env RVW_CODEX_SANDBOX=danger-full-access python -m rvw.container_entrypoint" in routes
    # The spike measures the production path, so it runs under the same explicit deadline.
    assert (
        "--deadline ${deadlineSeconds} --policy auto --publish none --json${policyArguments}"
        in routes
    )
    assert (
        "reviewScript(target.repoUrl, target.targetSha, config.reviewDeadlineSeconds, "
        "{model, reasoningEffort})"
    ) in routes
    assert "unset RVW_CODEX_DEFAULT_BASE_URL RVW_CODEX_SANDBOX" in routes


def test_worker_start_route_parses_codex_overrides_from_the_json_body() -> None:
    routes = (ROOT / "cloud/worker/src/routes.ts").read_text(encoding="utf-8")
    contract = (ROOT / "cloud/worker/src/spike-contract.ts").read_text(encoding="utf-8")

    assert "parseStartOverrides(body.body)" in routes
    assert "codexPolicyArguments(policy.model, policy.reasoningEffort)" in routes
    # Body override > Worker var > the container's own resolution, per field.
    assert "parsed.overrides.model ?? config.codexModel" in routes
    assert "parsed.overrides.reasoning_effort ?? config.codexReasoningEffort" in routes
    assert "model: model ?? null, reasoning_effort: reasoningEffort ?? null" in routes
    assert "return json({error: body.error}, {status: 400});" in routes
    assert "return json({error: parsed.error}, {status: 400});" in routes
    assert "export function parseStartOverrides(body: unknown)" in contract
    assert "start body has unsupported keys" in contract
    assert "import" not in contract.split("export function parseStartOverrides")[0].replace(
        "import-free", ""
    )


def test_cloud_codex_template_leaves_runtime_base_url_unconfigured() -> None:
    template = (ROOT / "docker/codex-config.toml").read_text(encoding="utf-8")

    assert "base_url" not in template


def test_egress_injection_emits_secret_free_structured_event() -> None:
    sandbox = (ROOT / "cloud/worker/src/sandbox.ts").read_text(encoding="utf-8")
    sandbox_config = (ROOT / "cloud/worker/src/sandbox-config.ts").read_text(encoding="utf-8")

    assert 'event: "codex_credential_injected"' in sandbox_config
    assert "JSON.stringify" in sandbox_config
    assert "interceptHttps = true" in sandbox
