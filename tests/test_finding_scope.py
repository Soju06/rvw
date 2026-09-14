"""Scope regression: controller diff evidence outranks discovery's severity."""

import hashlib
import json
from pathlib import Path

import pytest
from test_discover import FakeRuntime, registry, target, write_lane

from rvw.discover import EnrichedFinding, discover
from rvw.merge import merge
from rvw.schema import RuntimeFinding, Severity, Tier

DIFF = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -10,3 +10,4 @@
 before = 1
-old = 2
+new = 3
+more = 4
 after = 5
"""


async def scoped_discovery(tmp_path: Path):
    lane = "base-review"
    write_lane(tmp_path / "lanes", lane, Tier.BASE)
    cases = [
        ("inside", "src/a.py", 11, Severity.BLOCKER),
        ("old", "src/a.py", 99, Severity.BLOCKER),
        ("absent", "src/legacy.py", 5, Severity.BLOCKER),
        ("warning", "src/a.py", 12, Severity.WARNING),
        ("context", "src/a.py", 10, Severity.WARNING),
        ("file", "src/a.py", 0, Severity.BLOCKER),
        ("absent_file", "src/legacy.py", -1, Severity.BLOCKER),
        ("binary_file", "asset.bin", 0, Severity.BLOCKER),
        ("binary_line", "asset.bin", 5, Severity.BLOCKER),
    ]
    findings = [
        RuntimeFinding(rule_id=f"base/{rule}", file=file, line=line, severity=severity, body=rule)
        for rule, file, line, severity in cases
    ]
    resolved = target().model_copy(
        update={
            "diff": DIFF
            + "diff --git a/asset.bin b/asset.bin\nBinary files a/asset.bin and b/asset.bin differ\n",
            "changed_paths": ["src/a.py", "asset.bin"],
        }
    )
    return await discover(
        registry=registry((lane, Tier.BASE)),
        lanes_root=tmp_path / "lanes",
        target=resolved,
        runtime=FakeRuntime(findings={lane: findings}),
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
        replicas=1,
    )


async def test_discovery_classifies_real_hunks_and_preserves_raw_severity(tmp_path: Path) -> None:
    result = await scoped_discovery(tmp_path)
    expected = {
        "inside": ("changed", "blocker"),
        "old": ("unchanged_in_file", "info"),
        "absent": ("outside_diff", "info"),
        "warning": ("changed", "warning"),
        "context": ("changed", "warning"),
        "file": ("changed", "blocker"),
        "absent_file": ("outside_diff", "info"),
        "binary_file": ("changed", "blocker"),
        "binary_line": ("unchanged_in_file", "info"),
    }
    for finding in result.findings:
        data = finding.model_dump(mode="json")
        scope, severity = expected[finding.body]
        assert data["scope"] == scope
        assert data["effective_severity"] == severity
        assert data["demotion_reason"] == (None if scope == "changed" else scope)
        assert finding.severity is (
            Severity.WARNING if finding.body in {"warning", "context"} else Severity.BLOCKER
        )
    assert not next(f for f in result.findings if f.body == "context").anchorable
    groups = merge(result.findings, lane_tiers={"base-review": Tier.BASE}).groups
    for group in groups:
        data = group.model_dump(mode="json")
        assert (data["scope"], data["effective_severity"]) == expected[group.bodies[0]]
        assert data["demotion_reason"] == (None if data["scope"] == "changed" else data["scope"])


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        (["outside_diff", "unchanged_in_file"], "unchanged_in_file"),
        (["outside_diff", "unchanged_in_file", "changed"], "changed"),
    ],
)
def test_collapse_uses_strongest_member_scope(scopes: list[str], expected: str) -> None:
    findings = [
        EnrichedFinding.model_validate(
            dict(
                rule_id="base/rule",
                file="src/a.py",
                hunk_id="src/a.py:*",
                line=0,
                severity="blocker",
                body=f"member {i}",
                lane_id="base-review",
                replica=i,
                scope=scope,
            )
        )
        for i, scope in enumerate(scopes, start=1)
    ]
    group = merge(findings, lane_tiers={"base-review": Tier.BASE}).groups[0]
    data = group.model_dump(mode="json")
    assert data["scope"] == expected
    assert data["effective_severity"] == ("blocker" if expected == "changed" else "info")
    assert group.severity is Severity.BLOCKER
    assert group.agreement == len(scopes)
    assert len(group.findings) == len(scopes)


def test_runtime_finding_schema_remains_byte_identical() -> None:
    encoded = json.dumps(RuntimeFinding.model_json_schema(), sort_keys=True).encode()
    assert (
        hashlib.sha256(encoded).hexdigest()
        == "285767420e49c13161e5a39e2d63e511a76711061003a68c0b736fb8cb7e2135"
    )
