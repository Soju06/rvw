"""Regression contracts for Cloudflare remote state and registered App config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_terraform_module_has_no_backend_and_exposes_binding_outputs() -> None:
    versions = (ROOT / "cloud/infra/versions.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.10.0"' in versions
    assert 'backend "s3"' not in versions
    assert 'provider "cloudflare"' not in versions

    # Account-, environment-, and credential-specific values belong to consumers.
    for forbidden in (
        "r2.cloudflarestorage.com",
        "rvw-terraform-state",
        "access_key",
        "secret_key",
    ):
        assert forbidden not in versions

    outputs = (ROOT / "cloud/infra/outputs.tf").read_text(encoding="utf-8")
    for output in (
        "artifacts_bucket",
        "artifacts_bucket_id",
        "review_jobs_queue",
        "review_jobs_queue_id",
        "review_jobs_dlq",
        "review_jobs_dlq_id",
        "worker_name",
        "durable_object_classes",
    ):
        assert f'output "{output}"' in outputs


def test_state_bucket_bootstrap_is_explicit_and_secret_safe() -> None:
    bootstrap = (ROOT / "cloud/infra/bootstrap/README.md").read_text(encoding="utf-8")
    infra = (ROOT / "cloud/infra/README.md").read_text(encoding="utf-8")
    docs = f"{bootstrap}\n{infra}"

    assert "wrangler r2 bucket create rvw-terraform-state" in bootstrap
    assert "Object Read and Write" in bootstrap
    assert "specific bucket" in bootstrap
    assert "separate" in bootstrap.lower()
    assert "R2_STATE_ACCESS_KEY_ID" in docs
    assert "R2_STATE_SECRET_ACCESS_KEY" in docs
    assert "examples/deployer" in infra
    assert "terraform init -backend=false" in infra


def test_wrangler_environments_have_no_deployer_identity_defaults() -> None:
    config = json.loads((ROOT / "cloud/wrangler.jsonc").read_text(encoding="utf-8"))

    assert "GITHUB_APP_ID" not in config["vars"]
    assert "CODEX_PROXY_HOST" not in config["vars"]
    for environment in ("spike", "prod"):
        assert "GITHUB_APP_ID" not in config["env"][environment]["vars"]
        assert "CODEX_PROXY_HOST" not in config["env"][environment]["vars"]


def test_cloud_runbook_treats_app_manifest_as_deployer_template() -> None:
    readme = (ROOT / "cloud/README.md").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "cloud/github-app.manifest.json").read_text(encoding="utf-8"))

    assert "private" in readme.lower()
    assert manifest["url"] == "https://github.com/<your-org>/<your-fork>"
    assert manifest["hook_attributes"]["url"] == "https://<worker-host>/github/webhook"


def test_release_is_publish_only_and_notes_deployment_artifacts() -> None:
    workflow_path = ROOT / ".github/workflows/release.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert "deploy-cloud" not in workflow_text
    assert "RVW_CLOUD_DEPLOY" not in workflow_text
    assert "${RELEASE_REPOSITORY}/.github/workflows/rvw-deploy.yml@${RELEASE_TAG}" in workflow_text
    assert "github.com/${RELEASE_REPOSITORY}//cloud/infra?ref=${RELEASE_TAG}" in workflow_text


def test_reusable_deploy_workflow_declares_contract() -> None:
    workflow = cast(
        dict[str, Any],
        yaml.safe_load((ROOT / ".github/workflows/rvw-deploy.yml").read_text(encoding="utf-8")),
    )
    workflow_on = workflow.get("on", workflow.get(True))
    assert isinstance(workflow_on, dict)
    workflow_call = workflow_on["workflow_call"]
    inputs = workflow_call["inputs"]
    for name in (
        "environment",
        "rvw_ref",
        "worker_name",
        "codex_proxy_host",
        "github_app_id",
        "job_deadline_minutes",
        "account_id",
        "manage_terraform",
    ):
        assert name in inputs
    assert inputs["rvw_ref"]["required"] is True
    assert inputs["manage_terraform"]["default"] is True
    for name in (
        "CLOUDFLARE_API_TOKEN",
        "CODEX_API_KEY",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_WEBHOOK_SECRET",
        "RVW_ADMIN_TOKEN",
        "R2_STATE_ACCESS_KEY_ID",
        "R2_STATE_SECRET_ACCESS_KEY",
    ):
        assert name in workflow_call["secrets"]
    text = (ROOT / ".github/workflows/rvw-deploy.yml").read_text(encoding="utf-8")
    assert "terraform apply -auto-approve" in text
    assert "wrangler deploy --env" in text
    assert "wrangler secret put" in text
    assert "containers list --json" in text
    assert "/healthz" in text
