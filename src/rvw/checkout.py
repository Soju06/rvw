"""Provision and verify immutable repository workspaces for review runtimes."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

CheckoutFailureReason = Literal[
    "missing-base",
    "missing-checkout",
    "head-mismatch",
    "base-unresolvable",
    "head-unresolvable",
    "dirty-checkout",
    "diff-uncomputable",
    "provision-failed",
]
CommandRunner = Callable[[list[str]], str]


class CheckoutVerificationError(RuntimeError):
    """A checkout cannot prove that it represents the captured review range."""

    error_code = "checkout-verification-failed"

    def __init__(self, reason: CheckoutFailureReason, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{self.error_code}: {reason}: {detail}")

    def as_payload(self) -> dict[str, str]:
        return {"error": self.error_code, "reason": self.reason, "message": str(self)}


# The CLI's own clone and fetch run in the checkout phase, so the image's review-phase PATH
# shims pass them through to the real git and gh unchanged.
CHECKOUT_PHASE_ENVIRONMENT: Mapping[str, str] = {"RVW_PHASE": "checkout"}


def checkout_phase_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the environment for the CLI's own checkout commands."""

    return {**(os.environ if base is None else base), **CHECKOUT_PHASE_ENVIRONMENT}


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=checkout_phase_environment(),
    )
    return completed.stdout


def _checked_run(
    run: CommandRunner,
    command: list[str],
    *,
    reason: CheckoutFailureReason,
) -> str:
    try:
        return run(command)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or getattr(error, "stdout", None) or str(error)
        raise CheckoutVerificationError(
            reason,
            f"command failed: {shlex.join(command)}: {str(detail).strip()}",
        ) from error


def verify_checkout(
    checkout: Path,
    *,
    base_sha: str,
    head_sha: str,
    run: CommandRunner = _run,
) -> Path:
    """Verify exact anchors, cleanliness, and three-dot diff availability."""

    actual_head = _checked_run(
        run,
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        reason="head-unresolvable",
    ).strip()
    if actual_head != head_sha:
        raise CheckoutVerificationError(
            "head-mismatch",
            f"checkout HEAD {actual_head or '<empty>'} does not match captured head {head_sha}",
        )
    _checked_run(
        run,
        ["git", "-C", str(checkout), "cat-file", "-e", f"{base_sha}^{{commit}}"],
        reason="base-unresolvable",
    )
    _checked_run(
        run,
        ["git", "-C", str(checkout), "cat-file", "-e", f"{head_sha}^{{commit}}"],
        reason="head-unresolvable",
    )
    status = _checked_run(
        run,
        ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=all"],
        reason="dirty-checkout",
    ).strip()
    if status:
        raise CheckoutVerificationError("dirty-checkout", "review checkout must be clean")
    _checked_run(
        run,
        [
            "git",
            "-C",
            str(checkout),
            "diff",
            "--no-ext-diff",
            f"{base_sha}...{head_sha}",
            "--",
        ],
        reason="diff-uncomputable",
    )
    return checkout


def provision_checkout(
    *,
    repo: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    destination: Path,
    run: CommandRunner = _run,
) -> Path:
    """Provision a PR checkout and verify its captured review range."""

    provision_commands = [
        ["gh", "repo", "clone", repo, str(destination), "--", "--no-checkout"],
        [
            "git",
            "-C",
            str(destination),
            "fetch",
            "--no-tags",
            "origin",
            f"refs/pull/{pr_number}/head",
        ],
        ["git", "-C", str(destination), "fetch", "--no-tags", "origin", base_sha],
        ["git", "-C", str(destination), "checkout", "--detach", head_sha],
    ]
    for command in provision_commands:
        reason: CheckoutFailureReason = (
            "base-unresolvable" if command[-1] == base_sha else "provision-failed"
        )
        _checked_run(run, command, reason=reason)
    return verify_checkout(destination, base_sha=base_sha, head_sha=head_sha, run=run)


def provision_local_checkout(
    *,
    source: Path,
    base_sha: str,
    head_sha: str,
    destination: Path,
    run: CommandRunner = _run,
) -> Path:
    """Provision a detached local clone for a commit target."""

    for command in (
        ["git", "clone", "--no-checkout", "--shared", str(source), str(destination)],
        ["git", "-C", str(destination), "checkout", "--detach", head_sha],
    ):
        _checked_run(run, command, reason="provision-failed")
    return verify_checkout(destination, base_sha=base_sha, head_sha=head_sha, run=run)


__all__ = [
    "CHECKOUT_PHASE_ENVIRONMENT",
    "CheckoutFailureReason",
    "CheckoutVerificationError",
    "checkout_phase_environment",
    "provision_checkout",
    "provision_local_checkout",
    "verify_checkout",
]
