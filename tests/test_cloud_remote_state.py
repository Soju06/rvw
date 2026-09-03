"""Regression contracts for Cloudflare remote state and registered App config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_terraform_uses_partial_locked_r2_backend() -> None:
    versions = (ROOT / "cloud/infra/versions.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.10.0"' in versions
    assert 'backend "s3"' in versions
    assert "use_lockfile = true" in versions
    assert 'backend "local"' not in versions

    # Account-, environment-, and credential-specific values belong to init.
    for forbidden in (
        "r2.cloudflarestorage.com",
        "rvw-terraform-state",
        "terraform.tfstate",
        "access_key",
        "secret_key",
    ):
        assert forbidden not in versions


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
    assert "rvw/<environment>/terraform.tfstate" in infra
    assert "terraform init -backend=false" in infra


def test_every_wrangler_environment_uses_registered_app_id() -> None:
    config = json.loads((ROOT / "cloud/wrangler.jsonc").read_text(encoding="utf-8"))

    assert config["vars"]["GITHUB_APP_ID"] == "4813211"
    for environment in ("spike", "prod"):
        assert config["env"][environment]["vars"]["GITHUB_APP_ID"] == "4813211"


def test_cloud_runbook_names_registered_app_and_install_url() -> None:
    readme = (ROOT / "cloud/README.md").read_text(encoding="utf-8")

    assert "rvw-review" in readme
    assert "https://github.com/apps/rvw-review/installations/new" in readme


def test_release_initializes_r2_state_from_dedicated_secrets() -> None:
    workflow_path = ROOT / ".github/workflows/release.yml"
    workflow = cast(dict[str, Any], yaml.safe_load(workflow_path.read_text(encoding="utf-8")))
    deploy = workflow["jobs"]["deploy-cloud"]
    steps = deploy["steps"]
    terraform = next(step for step in steps if step.get("name") == "Apply Terraform resources")

    assert deploy["if"] == "vars.RVW_CLOUD_DEPLOY == 'true'"
    assert terraform["env"]["AWS_ACCESS_KEY_ID"] == ("${{ secrets.R2_STATE_ACCESS_KEY_ID }}")
    assert terraform["env"]["AWS_SECRET_ACCESS_KEY"] == (
        "${{ secrets.R2_STATE_SECRET_ACCESS_KEY }}"
    )

    script = terraform["run"]
    assert "terraform init" in script
    assert '-backend-config="bucket=rvw-terraform-state"' in script
    assert '-backend-config="key=rvw/prod/terraform.tfstate"' in script
    assert "r2.cloudflarestorage.com" in script
    assert "terraform init -backend=false" not in script
    assert script.index("terraform init") < script.index("terraform apply")

    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert workflow_text.index("terraform apply") < workflow_text.index(
        "npx wrangler deploy --env prod"
    )
