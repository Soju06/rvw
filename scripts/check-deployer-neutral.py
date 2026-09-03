#!/usr/bin/env python3
"""Reject deployer-specific identifiers from tracked shipping files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TOKENS = ("nekos", "vooy", "clawroid", "bori", "5addf0a1", "4813211")
SCOPES = ("cloud/", "src/", ".github/", "Dockerfile", "docker/", "docs/")
ACCOUNT_RE = re.compile(
    r"(?:account(?:[_ -]?id)?[^\n]{0,120}\b[0-9a-f]{32}\b|\b[0-9a-f]{32}\b[^\n]{0,120}account)",
    re.IGNORECASE,
)


def tracked_paths() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("unable to enumerate tracked files with git ls-files") from error
    return [
        path
        for path in result.stdout.splitlines()
        if any(path == scope.rstrip("/") or path.startswith(scope) for scope in SCOPES)
    ]


def main() -> int:
    findings: list[str] = []
    for name in tracked_paths():
        path = Path(name)
        test_name = (
            path.name.startswith("test_")
            or ".test." in path.name
            or ".spec." in path.name
            or path.stem.endswith("_test")
        )
        if (
            not path.is_file()
            or any(part in {"tests", "__tests__"} for part in path.parts)
            or test_name
        ):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            lowered = line.casefold()
            hits = [token for token in TOKENS if token in lowered]
            if hits or ACCOUNT_RE.search(line):
                reason = ", ".join(hits) if hits else "account identifier"
                findings.append(f"{name}:{number}: forbidden {reason}")
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        return 1
    print("deployer-neutral check: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
