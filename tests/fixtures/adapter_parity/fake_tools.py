"""Offline gh/Codex executables and container Python filesystem adapter.

Copied to a temporary PATH under each executable's name by the parity test.
The Python adapter supplies the image's baked template through the real
container entry point's supported template_path argument.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def record(tool: str, arguments: list[str]) -> None:
    descriptor = os.open(
        os.environ["RVW_PARITY_CALLS"], os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600
    )
    try:
        os.write(descriptor, (json.dumps({"tool": tool, "argv": arguments}) + "\n").encode())
    finally:
        os.close(descriptor)


def gh(arguments: list[str]) -> None:
    record("gh", arguments)
    fixture = json.loads(Path(os.environ["RVW_PARITY_TARGET"]).read_text())
    if arguments[:2] == ["pr", "view"]:
        assert arguments[2] == "42"
        assert arguments[arguments.index("--repo") + 1] == "fixture/project"
        print(json.dumps(fixture["metadata"]))
    elif arguments[:2] == ["pr", "diff"]:
        assert arguments[2] == "42"
        assert arguments[arguments.index("--repo") + 1] == "fixture/project"
        print("price.py" if "--name-only" in arguments else fixture["diff"])
    elif arguments[:2] == ["api", "repos/fixture/project/pulls/42"]:
        assert arguments[2:] == ["--jq", ".base.sha"]
        print(fixture["base"])
    elif arguments == ["--version"]:
        print("gh version offline-parity")
    else:
        raise AssertionError(f"unexpected gh invocation: {arguments!r}")


def codex(arguments: list[str]) -> None:
    record("codex", arguments)
    if arguments == ["--version"]:
        print("codex-cli offline-parity")
        return
    assert arguments[0] == "exec"
    assert arguments[-1] == "-"
    assert sys.stdin.read().strip(), "runtime must provide its real review prompt"
    mode = os.environ["RVW_PARITY_MODE"]
    if mode == "infra_failed":
        print("offline fixture: runtime unavailable")
        raise SystemExit(17)
    schema = json.loads(Path(arguments[arguments.index("--output-schema") + 1]).read_text())
    properties = schema["properties"]
    if "items" in properties:
        keys = properties["items"]["items"]["properties"]["group_key"]["enum"]
        result = {
            "items": [
                {
                    "group_key": key,
                    "verdict": "CONFIRMED",
                    "reason": "The changed price is two.",
                    "evidence": "price = 2",
                }
                for key in keys
            ]
        }
    else:
        findings = []
        finding_properties = properties["findings"]["items"]["properties"]
        if mode == "block" and "blocker" in finding_properties["severity"]["enum"]:
            findings.append(
                {
                    "rule_id": finding_properties["rule_id"]["enum"][0],
                    "file": "price.py",
                    "line": 1,
                    "severity": "blocker",
                    "body": "The fixture changes the required price from one to two.",
                }
            )
        result = {
            "verdict": "PASS" if not findings else "FAIL",
            "covered": ["price.py"],
            "findings": findings,
        }
    Path(arguments[arguments.index("-o") + 1]).write_text(json.dumps(result) + "\n")
    print("tokens used\n100")


def container_python(arguments: list[str]) -> None:
    assert arguments[:2] == ["-m", "rvw.container_entrypoint"]
    from rvw.container_entrypoint import run_entrypoint

    run_entrypoint(arguments[2:], template_path=Path(os.environ["RVW_PARITY_TEMPLATE"]))


if __name__ == "__main__":
    {"gh": gh, "codex": codex, "python": container_python}[Path(sys.argv[0]).name](sys.argv[1:])
