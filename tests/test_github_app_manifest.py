"""GitHub App manifest shape guard.

GitHub rejects manifests whose ``default_events`` list contains events that are
delivered to every App automatically or that are not enabled by the declared
permissions (measured 2026-09-03: ``installation`` and
``installation_repositories`` → "Default events unsupported" on the
organization manifest-creation page). Keep the checked-in manifest registrable.
"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "cloud" / "github-app.manifest.json"

# Delivered to every GitHub App regardless of subscription; not subscribable.
IMPLICIT_EVENTS = frozenset({"installation", "installation_repositories"})

# Minimum permission each subscribable event needs (GitHub webhook event docs).
EVENT_PERMISSION = {
    "pull_request": "pull_requests",
    "check_run": "checks",
    "check_suite": "checks",
    "pull_request_review": "pull_requests",
    "pull_request_review_comment": "pull_requests",
    "push": "contents",
}


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_has_no_implicit_default_events() -> None:
    events = set(_load()["default_events"])
    assert not (events & IMPLICIT_EVENTS), sorted(events & IMPLICIT_EVENTS)


def test_manifest_default_events_are_backed_by_permissions() -> None:
    manifest = _load()
    permissions = manifest["default_permissions"]
    for event in manifest["default_events"]:
        needed = EVENT_PERMISSION[event]
        assert permissions.get(needed) in {"read", "write"}, (event, needed)


def test_manifest_keeps_the_a1_events_and_permissions() -> None:
    manifest = _load()
    assert {"pull_request", "check_run"} <= set(manifest["default_events"])
    assert manifest["default_permissions"]["checks"] == "write"
    assert manifest["default_permissions"]["pull_requests"] == "write"
    assert manifest["public"] is False
