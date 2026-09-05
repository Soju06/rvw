from pathlib import Path

import pytest

from rvw.lane import load_new_lane
from rvw.registry import EffectiveRegistry, LaneSource


@pytest.fixture
def packaged() -> EffectiveRegistry:
    root = Path(__file__).parents[1] / "src/rvw/lanes"
    return EffectiveRegistry(
        LaneSource(load_new_lane(path), path, "packaged") for path in root.rglob("*.md")
    )


def test_packaged_rule_ownership(packaged: EffectiveRegistry) -> None:
    assert packaged.load_lane("contracts").rules == [
        "modeling/shapeless-data",
        "modeling/dict-overuse",
        "modeling/unclear-function-contract",
    ]
    assert len(packaged.load_lane("hygiene").rules) == 8
    assert len(packaged.load_lane("agent-tools").rules) == 13
    assert packaged.load_lane("lang-typescript").rules == ["slop/typing-bypass"]
    assert packaged.load_lane("lang-python").rules == ["slop/typing-bypass"]
    assert packaged.load_lane("test-integrity").rules == ["test-ci/critical-flaw"]
    assert packaged.load_lane("ci-integrity").rules == [
        "test-ci/fail-open-gate",
        "test-ci/wrong-artifact",
    ]
    assert packaged.load_lane("manifests").rules == ["deps/unused-added"]
    assert not any("deps/orphaned-remaining" in source.lane.rules for source in packaged.sources)


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/src/hooks/use-session.ts",
        "apps/web/src/api/client.js",
        "Card.tsx",
        "src/Card.tsx",
        "main.py",
        "main.go",
        "scripts/build.ts",
        "README.md",
    ],
)
def test_frontend_and_language_alone_do_not_activate_backend(
    packaged: EffectiveRegistry, path: str
) -> None:
    assert "backend-observability" not in {x.id for x in packaged.activate("owner/repo", [path])}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("server/main.ts", {"backend-observability", "lang-typescript"}),
        ("services/backend/run.py", {"backend-observability", "lang-python"}),
        ("tools/search.py", {"agent-tools", "lang-python"}),
        ("search_tool.ts", {"agent-tools", "lang-typescript"}),
        ("src/tool/search.py", {"agent-tools", "lang-python"}),
        ("toolpacks/search/index.ts", {"agent-tools", "lang-typescript"}),
        ("test_search.py", {"test-integrity", "lang-python"}),
        ("src/search_test.py", {"test-integrity", "lang-python"}),
        (".github/workflows/ci.yml", {"ci-integrity"}),
        ("packages/app/package.json", {"manifests"}),
        ("uv.lock", {"manifests"}),
    ],
)
def test_domain_activation(packaged: EffectiveRegistry, path: str, expected: set[str]) -> None:
    ids = {x.id for x in packaged.activate("owner/repo", [path])}
    assert (
        ids - {"correctness", "contracts", "hygiene", "security-exposure", "dynamic/goal-parity"}
        == expected
    )


def test_mixed_diff_scope_prompts_bound_finding_locations(packaged: EffectiveRegistry) -> None:
    paths = ["server/job.ts", "tools/search.py", "Card.tsx", "README.md"]
    ids = {x.id for x in packaged.activate("owner/repo", paths)}
    assert {"backend-observability", "agent-tools", "frontend/skeleton-parity"} <= ids
    for source in packaged.sources:
        if source.lane.tier.value == "scope":
            assert "finding locations" in source.lane.prompt_body.lower()
