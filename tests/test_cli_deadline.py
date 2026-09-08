from __future__ import annotations

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module

runner = CliRunner()


@pytest.mark.parametrize("deadline", ["0", "1801"])
@pytest.mark.parametrize(
    "args",
    [
        ["review", "--target", "HEAD"],
        ["gate", "--target", "42"],
        ["auto", "--target", "HEAD"],
        ["stack", "review", "--prs", "1,2"],
        ["sample", "--lane", "test-lane", "--fixture", "fixture.py"],
    ],
)
def test_runtime_commands_reject_deadline_outside_cli_bounds_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    deadline: str,
) -> None:
    def forbidden_host_gate() -> None:
        raise AssertionError("invalid deadline reached command execution")

    monkeypatch.setattr(cli_module, "_command_host_gate", forbidden_host_gate)

    result = runner.invoke(cli_module.app, [*args, "--deadline", deadline])

    assert result.exit_code == 2


@pytest.mark.parametrize("value", ["0", "1801"])
@pytest.mark.parametrize(
    "args",
    [
        ["review", "--target", "HEAD"],
        ["gate", "--target", "42"],
        ["auto", "--target", "HEAD"],
        ["stack", "review", "--prs", "1,2"],
    ],
)
def test_runtime_commands_reject_no_output_timeout_outside_cli_bounds_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    value: str,
) -> None:
    def forbidden_host_gate() -> None:
        raise AssertionError("invalid no-output timeout reached command execution")

    monkeypatch.setattr(cli_module, "_command_host_gate", forbidden_host_gate)

    result = runner.invoke(cli_module.app, [*args, "--no-output-timeout", value])

    assert result.exit_code == 2
