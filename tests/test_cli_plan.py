from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module
from rvw.cli import EXIT_NOT_FOUND, app
from rvw.target import ResolvedTarget, TargetResolutionError

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    base = root / "lanes" / "base"
    scope = root / "lanes" / "scope" / "frontend"
    base.mkdir(parents=True)
    scope.mkdir(parents=True)
    (root / "layers.yaml").write_text(
        """layers:
  - id: base
    tier: base
    lanes: [slop-hygiene, unscoped-sweep]
  - id: scope/frontend
    tier: scope
    when:
      paths: ["src/**"]
    lanes: [frontend/check]
""",
        encoding="utf-8",
    )
    for name in ("slop-hygiene.md", "unscoped-sweep.md"):
        (base / name).write_text(
            (FIXTURES / "lanes" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (scope / "check.md").write_text(
        """---
lane: frontend/check
tier: scope
cost: light
validation: pending
rules:
  - frontend/check
---

# frontend/check

Check frontend behavior.
""",
        encoding="utf-8",
    )
    return root


def canned_target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
        repo="fixture/local",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/view.ts"],
        diff="diff --git a/src/view.ts b/src/view.ts\n",
    )


def large_target() -> ResolvedTarget:
    paths = [f"src/chunk-{index}.ts" for index in range(3)]
    diff = "".join(
        (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            f"+{'x' * 149_900}\n"
        )
        for path in paths
    )
    return canned_target().model_copy(update={"changed_paths": paths, "diff": diff})


def test_plan_json_shape_tier_zero_predicates_and_lpt_order(
    monkeypatch: pytest.MonkeyPatch, registry_root: Path
) -> None:
    def fake_resolve_target(spec: str, *, cwd: Path) -> ResolvedTarget:
        del spec, cwd
        return canned_target()

    monkeypatch.setattr(cli_module, "resolve_target", fake_resolve_target)

    result = runner.invoke(
        app,
        ["plan", "--target", "HEAD", "--json", "--registry", str(registry_root)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["target"] == {
        "kind": "commit",
        "repo": "fixture/local",
        "head_sha": "b" * 40,
        "pr_number": None,
    }
    assert payload["brief_source"] is None
    assert payload["replicas"] == 1
    assert payload["adjudicate_replicas"] == 3
    assert payload["chunk_count"] == 1
    assert payload["total_runs"] == 3
    assert {lane["lane"] for lane in payload["lanes"]} >= {
        "slop-hygiene",
        "unscoped-sweep",
    }
    layers = {layer["id"]: layer for layer in payload["layers"]}
    assert layers["base"]["predicate"] is None
    assert layers["scope/frontend"]["predicate"] == {"paths": ["src/**"]}
    assert payload["dispatch_order"] == [
        "unscoped-sweep",
        "slop-hygiene",
        "frontend/check",
    ]
    assert payload["lanes"] == [
        {
            "lane": "slop-hygiene",
            "tier": "base",
            "cost": "normal",
            "rules_count": 6,
            "replicas": 1,
        },
        {
            "lane": "unscoped-sweep",
            "tier": "base",
            "cost": "heavy",
            "rules_count": 4,
            "replicas": 1,
        },
        {
            "lane": "frontend/check",
            "tier": "scope",
            "cost": "light",
            "rules_count": 1,
            "replicas": 1,
        },
    ]


def test_plan_preserves_split_replica_overrides(
    monkeypatch: pytest.MonkeyPatch, registry_root: Path
) -> None:
    monkeypatch.setattr(cli_module, "_resolve_cli_target", lambda spec: canned_target())

    result = runner.invoke(
        app,
        [
            "plan",
            "--target",
            "HEAD",
            "--replicas",
            "2",
            "--adjudicate-replicas",
            "1",
            "--json",
            "--registry",
            str(registry_root),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["replicas"] == 2
    assert payload["adjudicate_replicas"] == 1
    assert payload["total_runs"] == 6
    assert {lane["replicas"] for lane in payload["lanes"]} == {2}


def test_plan_reports_chunk_expanded_total_runs(
    monkeypatch: pytest.MonkeyPatch, registry_root: Path
) -> None:
    def fake_resolve_target(spec: str, *, cwd: Path) -> ResolvedTarget:
        del spec, cwd
        return large_target()

    monkeypatch.setattr(cli_module, "resolve_target", fake_resolve_target)

    result = runner.invoke(
        app,
        ["plan", "--target", "HEAD", "--json", "--registry", str(registry_root)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["chunk_count"] == 2
    assert payload["total_runs"] == 6


def test_head_falls_back_to_local_git_when_no_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_resolver(spec: str, *, cwd: Path) -> ResolvedTarget:
        del cwd
        if spec == "HEAD":
            raise ValueError("symbolic revisions are unsupported")
        raise TargetResolutionError(["gh", "repo", "view"], "no git remotes found")

    monkeypatch.setattr(cli_module, "resolve_target", unavailable_resolver)

    resolved = cli_module._resolve_cli_target("HEAD")

    assert resolved.kind == "commit"
    assert resolved.repo == Path.cwd().name
    assert len(resolved.head_sha) == 40
    assert resolved.diff


def test_lanes_list_shows_every_registered_lane(registry_root: Path) -> None:
    result = runner.invoke(app, ["lanes", "list", "--registry", str(registry_root)])

    assert result.exit_code == 0, result.stdout
    assert "slop-hygiene" in result.stdout
    assert "unscoped-sweep" in result.stdout
    assert "frontend/check" in result.stdout
    assert "pending" in result.stdout


def test_lanes_show_prints_path_frontmatter_rules_and_body(registry_root: Path) -> None:
    result = runner.invoke(
        app, ["lanes", "show", "unscoped-sweep", "--registry", str(registry_root)]
    )

    assert result.exit_code == 0, result.stdout
    assert str(registry_root / "lanes" / "base" / "unscoped-sweep.md") in result.stdout
    assert "lane: unscoped-sweep" in result.stdout
    assert "unscoped/correctness" in result.stdout
    assert "# unscoped-sweep" in result.stdout


def test_lanes_show_unknown_id_exits_not_found(registry_root: Path) -> None:
    result = runner.invoke(app, ["lanes", "show", "unknown-lane", "--registry", str(registry_root)])

    assert result.exit_code == EXIT_NOT_FOUND
    assert "unknown lane" in result.stderr
