"""Offline contracts for the GitHub CLI installed in container images."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = ("cloud/Dockerfile", "Dockerfile")


def _argument(dockerfile: str, name: str) -> str:
    match = re.search(rf"^ARG {re.escape(name)}=(?P<value>[^\s]+)$", dockerfile, re.MULTILINE)
    assert match is not None, f"missing ARG {name}"
    return match.group("value").strip('"')


@pytest.mark.parametrize("relative_path", DOCKERFILES)
def test_container_pins_and_verifies_official_gh_release(relative_path: str) -> None:
    dockerfile = (ROOT / relative_path).read_text(encoding="utf-8")
    normalized = dockerfile.replace("\\\n", " ")

    apt_package_lists = re.findall(
        r"apt-get install\s+(?P<packages>.*?)\s*&&",
        normalized,
    )
    assert apt_package_lists, "expected an apt-get install package list"
    for package_list in apt_package_lists:
        assert "gh" not in shlex.split(package_list)

    gh_version = _argument(dockerfile, "GH_VERSION")
    minimum_version = _argument(dockerfile, "MIN_GH_VERSION")
    assert re.fullmatch(r"v?\d+\.\d+\.\d+", gh_version)
    assert re.fullmatch(r"v?\d+\.\d+\.\d+", minimum_version)

    assert "COPY docker/install-gh.sh /usr/local/lib/rvw/install-gh.sh" in dockerfile
    assert "RUN sh /usr/local/lib/rvw/install-gh.sh" in dockerfile
    checksum_step = (ROOT / "docker/install-gh.sh").read_text(encoding="utf-8")
    assert "https://github.com/cli/cli/releases/download/${GH_VERSION}" in checksum_step
    assert "sha256sum --check" in checksum_step
    assert "GH_SHA256" in checksum_step
    assert "install --mode=0755" in checksum_step
    assert "/usr/local/bin/gh" in checksum_step
    assert "gh --version" in checksum_step
    assert 'dpkg --compare-versions "${installed_version}" ge "${MIN_GH_VERSION}"' in checksum_step


def test_both_images_share_identical_gh_pins() -> None:
    pins = [
        tuple(
            _argument((ROOT / filename).read_text(), name)
            for name in ("GH_VERSION", "GH_SHA256", "MIN_GH_VERSION")
        )
        for filename in DOCKERFILES
    ]
    assert pins[0] == pins[1]
