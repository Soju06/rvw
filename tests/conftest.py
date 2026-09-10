"""Keep the new remote policy lookup offline unless a test installs an API fake."""

import pytest


@pytest.fixture(autouse=True)
def offline_execution_policy_api(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    if request.node.get_closest_marker("live") is not None:
        return
    import rvw.cli as cli

    monkeypatch.setattr(cli, "_read_execution_repository_policy", lambda *_, **__: None)
