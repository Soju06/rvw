from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module
import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.diffbudget import apply_diff_budget
from rvw.discover import DiscoverResult, EnrichedFinding
from rvw.merge import merge
from rvw.sample import SampleReport, SampleSiteVariance
from rvw.schema import Tier, Verdict
from rvw.store import RunStore
from rvw.target import ResolvedTarget

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def policy_file(tmp_path: Path, publish_state: str = "comment") -> Path:
    path = tmp_path / "auto.yaml"
    path.write_text(
        f"""promote_to_blocker:
  agreement_at_least: 2
  severity_at_least: warning
drop:
  agreement_at_most: 1
  severity_at_most: suggestion
block_when:
  severity_at_least: blocker
publish_state: {publish_state}
""",
        encoding="utf-8",
    )
    return path


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["a.py"],
        diff="diff --git a/a.py b/a.py\n",
        pr_number=42,
    )


def fixture_artifacts(tmp_path: Path, *, adjudicated: bool) -> cli_module._PipelineArtifacts:
    raw_findings = json.loads((FIXTURES / "smoke_1119_findings.json").read_text(encoding="utf-8"))
    findings = [EnrichedFinding.model_validate(item) for item in raw_findings]
    lane_tiers = {
        finding.lane_id: (Tier.DYNAMIC if finding.lane_id.startswith("dynamic/") else Tier.BASE)
        for finding in findings
    }
    merged = merge(findings, lane_tiers=lane_tiers)
    outcome = None
    if adjudicated:
        raw = json.loads((FIXTURES / "smoke_1119_outcome.json").read_text(encoding="utf-8"))
        outcome = AdjudicationOutcome(
            verdicts={key: Verdict(value) for key, value in raw["verdicts"].items()},
            reasons=raw["reasons"],
            evidence=raw["evidence"],
            replica_votes={
                key: [Verdict(value) for value in votes]
                for key, votes in raw["replica_votes"].items()
            },
            unresolved=raw["unresolved"],
            coerced_rejections=raw["coerced_rejections"],
        )
    run = RunStore(tmp_path / "runs").create(target())
    report_path = run.dir / "report.md"
    report_path.write_text("# report\n", encoding="utf-8")
    return cli_module._PipelineArtifacts(
        run=run,
        target=target(),
        discovered=DiscoverResult(lane_results={}, findings=findings, coverage=[]),
        merged=merged,
        outcome=outcome,
        report_md="# report\n",
        report_path=report_path,
    )


def patch_pipeline(
    monkeypatch: pytest.MonkeyPatch, artifacts: cli_module._PipelineArtifacts
) -> None:
    async def fake_execute_pipeline(**kwargs: object) -> cli_module._PipelineArtifacts:
        del kwargs
        return artifacts

    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_execute_pipeline)


@pytest.mark.parametrize(
    ("adjudicated", "verdict", "exit_code"),
    [(False, "PASS", 0), (True, "BLOCK", 1)],
)
def test_auto_json_verdict_and_exit_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adjudicated: bool,
    verdict: str,
    exit_code: int,
) -> None:
    artifacts = fixture_artifacts(tmp_path, adjudicated=adjudicated)
    patch_pipeline(monkeypatch, artifacts)
    result = runner.invoke(
        cli_module.app,
        [
            "auto",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path, "none")),
            "--json",
        ],
    )
    assert result.exit_code == exit_code, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == verdict
    assert set(payload) == {
        "run_id",
        "verdict",
        "blocking",
        "dropped",
        "promoted",
        "considered",
        "report_path",
    }


def test_auto_policy_none_skips_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_pipeline(monkeypatch, fixture_artifacts(tmp_path, adjudicated=False))

    def forbidden_publish(**kwargs: object) -> None:
        raise AssertionError(f"publish called: {kwargs}")

    monkeypatch.setattr(cli_module, "publish_review", forbidden_publish)
    result = runner.invoke(
        cli_module.app,
        ["auto", "--target", "42", "--policy", str(policy_file(tmp_path, "none"))],
    )
    assert result.exit_code == 0, result.stdout


def test_auto_forwards_split_replica_defaults_overrides_and_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    artifacts = fixture_artifacts(tmp_path, adjudicated=False)

    async def fake_execute_pipeline(**kwargs: object) -> cli_module._PipelineArtifacts:
        calls.append(kwargs)
        return artifacts

    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_execute_pipeline)
    default_result = runner.invoke(
        cli_module.app,
        [
            "auto",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path, "none")),
        ],
    )
    result = runner.invoke(
        cli_module.app,
        [
            "auto",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path, "none")),
            "--replicas",
            "2",
            "--adjudicate-replicas",
            "1",
            "--concurrency",
            "4",
        ],
    )

    assert default_result.exit_code == 0, default_result.stdout
    assert result.exit_code == 0, result.stdout
    assert calls[0]["discover_replicas"] == 1
    assert calls[0]["adjudicate_replicas"] == 3
    assert calls[1]["discover_replicas"] == 2
    assert calls[1]["adjudicate_replicas"] == 1
    assert calls[1]["concurrency"] == 4


def test_allow_approve_is_placeholder_and_payload_remains_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_pipeline(monkeypatch, fixture_artifacts(tmp_path, adjudicated=False))
    payloads: list[dict[str, object]] = []

    def fake_run(cmd: list[str], input_json: str) -> str:
        del cmd
        payloads.append(json.loads(input_json))
        return json.dumps({"html_url": "https://example.test/review/1"})

    monkeypatch.setattr(publish_module, "_run", fake_run)
    result = runner.invoke(
        cli_module.app,
        [
            "auto",
            "--target",
            "42",
            "--policy",
            str(policy_file(tmp_path)),
            "--allow-approve",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "approve publishing is not implemented" in result.stderr
    assert payloads and {payload["event"] for payload in payloads} == {"COMMENT"}


@pytest.fixture
def sample_registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    lanes = root / "lanes" / "base"
    lanes.mkdir(parents=True)
    (root / "layers.yaml").write_text(
        "layers:\n  - id: base\n    tier: base\n    lanes: [test-lane]\n",
        encoding="utf-8",
    )
    (lanes / "test-lane.md").write_text(
        """---
lane: test-lane
tier: base
rules: [test/rule]
validation: pending
---
Find issues.
""",
        encoding="utf-8",
    )
    fixture = tmp_path / "fixture.py"
    fixture.write_text("problem = True\n", encoding="utf-8")
    return root


def sample_diff_segment(path: str, body: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+{body}\n"


def test_fixture_diff_passes_through_large_unified_diff_with_original_budget(
    tmp_path: Path,
) -> None:
    original = "".join(
        sample_diff_segment(f"providers/tabelog/file-{index}.ts", "x" * 146_900)
        for index in range(5)
    )
    assert 734_000 < len(original) < 736_000
    fixture = tmp_path / "fixture.diff"
    fixture.write_text(original, encoding="utf-8")

    fixture_diff = cli_module._fixture_diff(fixture)
    chunks, budget = apply_diff_budget(fixture_diff)

    assert fixture_diff == original
    assert budget.kept_chars == len(original)
    assert budget.excluded_reason == {}
    assert budget.chunk_count >= 2
    assert "".join(chunk.text for chunk in chunks) == original


def test_fixture_diff_passes_through_traditional_unified_diff(tmp_path: Path) -> None:
    original = "--- a/source.py\n+++ b/source.py\n@@ -1 +1 @@\n-old\n+new\n"
    fixture = tmp_path / "traditional.diff"
    fixture.write_text(original, encoding="utf-8")

    assert cli_module._fixture_diff(fixture) == original


def test_fixture_diff_keeps_ordinary_source_file_conversion(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.py"
    fixture.write_text("problem = True\n", encoding="utf-8")

    fixture_diff = cli_module._fixture_diff(fixture)

    assert fixture_diff.startswith("diff --git ")
    assert "--- /dev/null\n" in fixture_diff
    assert "+problem = True\n" in fixture_diff


def test_sample_empty_review_json_is_user_error(
    tmp_path: Path,
    sample_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tmp_path / "oversized.diff"
    fixture.write_text(sample_diff_segment("src/large.py", "x" * 767_000), encoding="utf-8")

    class NoRuntime:
        async def execute_raw(self, **kwargs: object) -> object:
            raise AssertionError(f"runtime must not execute: {kwargs}")

    monkeypatch.setattr(cli_module, "CodexRuntime", NoRuntime)

    result = runner.invoke(
        cli_module.app,
        [
            "sample",
            "--lane",
            "test-lane",
            "--fixture",
            str(fixture),
            "--registry",
            str(sample_registry),
            "--json",
        ],
    )

    assert result.exit_code == 2, result.stdout
    assert json.loads(result.stdout) == {
        "error": "empty-review-diff",
        "message": "fixture produced an empty review diff; excluded: [src/large.py (oversize-file)]",
        "excluded_reason": {"src/large.py": "oversize-file"},
    }


@pytest.mark.parametrize(("verdict", "exit_code"), [("PASS", 0), ("REVIEW", 1)])
def test_sample_exit_codes_and_pass_hint(
    tmp_path: Path,
    sample_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: str,
    exit_code: int,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_sample(*args: object, **kwargs: object) -> SampleReport:
        del args
        calls.append(kwargs)
        return SampleReport(
            lane_id="test-lane",
            enum_findings=[("test/rule", 1)],
            free_findings=[("free/rule", 1)],
            enum_only=[],
            free_only=[("test/rule", 2)] if verdict == "PASS" else [("free/extra", 2)],
            novel_rule_ids=[] if verdict == "PASS" else ["free/extra"],
            site_variance=(
                [
                    SampleSiteVariance(
                        variant="free_only",
                        rule_id="test/rule",
                        file="fixture.py",
                        line=2,
                    )
                ]
                if verdict == "PASS"
                else []
            ),
            verdict=cast(Literal["PASS", "REVIEW"], verdict),
            replicas=3,
            chunk_count=1,
        )

    monkeypatch.setattr(cli_module, "sample_lane", fake_sample)
    result = runner.invoke(
        cli_module.app,
        [
            "sample",
            "--lane",
            "test-lane",
            "--fixture",
            str(tmp_path / "fixture.py"),
            "--registry",
            str(sample_registry),
            "--concurrency",
            "4",
        ],
    )
    assert result.exit_code == exit_code, result.stdout
    assert calls[0]["concurrency"] == 4
    assert ("may drop 'validation: pending'" in result.stdout) is (verdict == "PASS")
    if verdict == "PASS":
        assert "site variance" in result.stdout


def test_sample_json_separates_novel_rules_and_site_variance(
    tmp_path: Path,
    sample_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sample(*args: object, **kwargs: object) -> SampleReport:
        del args, kwargs
        return SampleReport(
            lane_id="test-lane",
            enum_findings=[("test/rule", 1)],
            free_findings=[("test/rule", 2)],
            enum_only=[("test/rule", 1)],
            free_only=[("test/rule", 2)],
            novel_rule_ids=[],
            site_variance=[
                SampleSiteVariance(
                    variant="free_only",
                    rule_id="test/rule",
                    file="fixture.py",
                    line=2,
                )
            ],
            verdict="PASS",
            replicas=3,
            chunk_count=1,
        )

    monkeypatch.setattr(cli_module, "sample_lane", fake_sample)
    result = runner.invoke(
        cli_module.app,
        [
            "sample",
            "--lane",
            "test-lane",
            "--fixture",
            str(tmp_path / "fixture.py"),
            "--registry",
            str(sample_registry),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["novel_rule_ids"] == []
    assert payload["site_variance"] == [
        {
            "variant": "free_only",
            "rule_id": "test/rule",
            "file": "fixture.py",
            "line": 2,
        }
    ]


def test_doctor_cli_empty_and_fixture_store(tmp_path: Path) -> None:
    empty = runner.invoke(cli_module.app, ["doctor", "--store", str(tmp_path / "empty")])
    run = tmp_path / "store" / "run"
    run.mkdir(parents=True)
    (run / "discover.json").write_text(
        json.dumps(
            {
                "findings": [],
                "coverage": [
                    {
                        "lane_id": "lane",
                        "dispatched": 3,
                        "valid": 2,
                        "findings": 0,
                        "runs": [
                            {
                                "replica": replica,
                                "chunk": 1,
                                "valid": replica < 3,
                                "findings": 0,
                                "invalid_reason": (None if replica < 3 else "scripted_invalid"),
                            }
                            for replica in range(1, 4)
                        ],
                    }
                ],
                "budget": None,
            }
        ),
        encoding="utf-8",
    )
    populated = runner.invoke(cli_module.app, ["doctor", "--store", str(tmp_path / "store")])
    assert empty.exit_code == 0
    assert "Runs scanned: 0" in empty.stdout
    assert populated.exit_code == 0
    assert "lane" in populated.stdout
    assert "invalid" in populated.stdout
