"""Regression tests for the tracked deployer-neutrality guard."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_guard(tmp_path: Path, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "scripts/check-deployer-neutral.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/check-deployer-neutral.py", script)
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, text=True, capture_output=True
    )


def test_guard_reports_forbidden_tokens_and_account_ids(tmp_path: Path) -> None:
    result = run_guard(
        tmp_path,
        {
            "cloud/config.txt": "hostname = NEKOS.example\naccount = 0123456789abcdef0123456789abcdef\n",
            "docs/guide.md": "product: VoOy\n",
        },
    )

    assert result.returncode == 1
    assert "cloud/config.txt:1:" in result.stderr
    assert "cloud/config.txt:2:" in result.stderr
    assert "docs/guide.md:1:" in result.stderr


def test_guard_allows_project_urls_and_excludes_tests(tmp_path: Path) -> None:
    result = run_guard(
        tmp_path,
        {
            "docs/guide.md": (
                "https://github.com/Soju06/rvw\n"
                "ghcr.io/soju06/rvw:v1\n"
                "account key = 0123456789abcdef0123456789abcdef01234567\n"
            ),
            "cloud/worker/src/example.test.ts": "nekos vooy clawroid bori 5addf0a1\n",
            "tests/test_example.py": "4813211\n",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "deployer-neutral check: clean\n"
