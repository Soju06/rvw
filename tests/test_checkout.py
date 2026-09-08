from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import rvw.checkout as checkout_module
from rvw.checkout import (
    CHECKOUT_PHASE_ENVIRONMENT,
    CheckoutVerificationError,
    checkout_phase_environment,
    provision_checkout,
    verify_checkout,
)

BASE = "a" * 40
HEAD = "b" * 40


def test_verify_checkout_checks_anchors_cleanliness_and_three_dot_diff(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        commands.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return f"{HEAD}\n"
        return ""

    assert verify_checkout(checkout, base_sha=BASE, head_sha=HEAD, run=fake_run) == checkout
    assert commands == [
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        ["git", "-C", str(checkout), "cat-file", "-e", f"{BASE}^{{commit}}"],
        ["git", "-C", str(checkout), "cat-file", "-e", f"{HEAD}^{{commit}}"],
        ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=all"],
        ["git", "-C", str(checkout), "diff", "--no-ext-diff", f"{BASE}...{HEAD}", "--"],
    ]


@pytest.mark.parametrize(
    ("failed_token", "reason"),
    [(f"{BASE}^{{commit}}", "base-unresolvable"), (f"{BASE}...{HEAD}", "diff-uncomputable")],
)
def test_verify_checkout_failure_is_machine_readable(
    tmp_path: Path, failed_token: str, reason: str
) -> None:
    def fake_run(command: list[str]) -> str:
        if command[-2:] == ["rev-parse", "HEAD"]:
            return HEAD
        if failed_token in command:
            raise subprocess.CalledProcessError(128, command, stderr="scripted failure")
        return ""

    with pytest.raises(CheckoutVerificationError) as caught:
        verify_checkout(tmp_path / "checkout", base_sha=BASE, head_sha=HEAD, run=fake_run)

    assert caught.value.error_code == "checkout-verification-failed"
    assert caught.value.reason == reason
    assert caught.value.as_payload() == {
        "error": "checkout-verification-failed",
        "reason": reason,
        "message": str(caught.value),
    }


def test_provision_checkout_fetches_base_and_uses_shared_verifier(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        commands.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return HEAD
        return ""

    provision_checkout(
        repo="owner/repo",
        pr_number=42,
        base_sha=BASE,
        head_sha=HEAD,
        destination=checkout,
        run=fake_run,
    )

    assert ["git", "-C", str(checkout), "fetch", "--no-tags", "origin", BASE] in commands
    assert [
        "git",
        "-C",
        str(checkout),
        "diff",
        "--no-ext-diff",
        f"{BASE}...{HEAD}",
        "--",
    ] in commands


def test_default_runner_marks_the_checkout_phase_and_preserves_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Completed:
        stdout = "ok\n"

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        observed["command"] = command
        observed.update(kwargs)
        return Completed()

    monkeypatch.setenv("RVW_PHASE", "review")
    monkeypatch.setenv("RVW_PHASE_PROBE", "kept")
    monkeypatch.setattr(checkout_module.subprocess, "run", fake_run)

    assert checkout_module._run(["git", "fetch", "origin", BASE]) == "ok\n"
    env = observed["env"]
    assert isinstance(env, dict)
    assert env["RVW_PHASE"] == "checkout"
    assert env["RVW_PHASE_PROBE"] == "kept"
    assert observed["command"] == ["git", "fetch", "origin", BASE]
    assert observed["check"] is True and observed["capture_output"] is True
    assert dict(CHECKOUT_PHASE_ENVIRONMENT) == {"RVW_PHASE": "checkout"}
    assert checkout_phase_environment({"PATH": "/usr/bin"}) == {
        "PATH": "/usr/bin",
        "RVW_PHASE": "checkout",
    }
