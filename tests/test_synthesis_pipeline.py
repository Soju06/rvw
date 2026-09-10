"""Synthesis uses retained artifacts and never changes diagnostic judgments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import rvw.cli as cli
import rvw.pipeline as pipeline
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, DiscoveryMode
from rvw.merge import merge
from rvw.presentation import PresentationConfig, SynthesisConfig
from rvw.store import RunStore
from rvw.summary import ExecutionSummary, execution_summary, summarize_run
from rvw.synthesis import SynthesisDocument, SynthesisFacts
from rvw.target import ResolvedTarget


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        pr_number=1800,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=[],
        diff="",
        pr_title="Make account lookup reliable",
        pr_body="Keep account errors explicit.",
    )


def outcome() -> AdjudicationOutcome:
    return AdjudicationOutcome(
        verdicts={},
        reasons={},
        evidence={},
        replica_votes={},
        unresolved=[],
        coerced_rejections=0,
    )


def document() -> SynthesisDocument:
    return SynthesisDocument(
        overview="This change makes account lookup reliable. The available checks found no issue.",
        first_action=None,
        findings=[],
    )


@pytest.mark.parametrize("fallback", [False, True])
async def test_pipeline_synthesizes_persisted_inputs_and_retains_facts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fallback: bool,
) -> None:
    original_target = target()
    run = RunStore(tmp_path).create(original_target)
    discovered = DiscoverResult(lane_results={}, findings=[], coverage=[])
    original_outcome = outcome()
    presentation = PresentationConfig(locale="en", display_name="Repository Review")
    received: list[dict[str, Any]] = []
    selected_runtime: Any = object()
    facts = SynthesisFacts(
        status="fallback:schema-invalid" if fallback else "ok",
        model="configured-model",
        reasoning_effort="high",
        wall_seconds=4.5,
        tool_calls=0,
    )

    async def discover(**_: object) -> DiscoverResult:
        return discovered

    async def adjudicate(*_: object, **__: object) -> AdjudicationOutcome:
        # Memory changes after target persistence must not become synthesis input.
        original_target.pr_title = "UNPERSISTED"
        return original_outcome

    async def synthesize(**kwargs: Any) -> tuple[SynthesisDocument | None, SynthesisFacts]:
        assert (run.dir / "outcome.json").is_file()
        assert (run.dir / "merge.json").is_file()
        assert (run.dir / "discover.json").is_file()
        assert kwargs["target"] == run.load_target()
        assert kwargs["target"].pr_title == "Make account lookup reliable"
        assert kwargs["outcome"] == run.load_outcome()
        assert kwargs["outcome"] is not original_outcome
        assert kwargs["merged"] == run.load_merge()
        assert kwargs["presentation"] == run.load_presentation()
        assert kwargs["runtime"] is selected_runtime
        received.append(kwargs)
        return (None if fallback else document()), facts

    monkeypatch.setattr(pipeline, "discover", discover)
    monkeypatch.setattr(pipeline, "synthesize", synthesize)
    unused: Any = None
    artifacts = await pipeline.execute_pipeline(
        registry=unused,
        lanes_root=tmp_path,
        target=original_target,
        active_lanes=[],
        runtime=unused,
        adjudication_runtime=selected_runtime,
        adjudicator=adjudicate,
        repo_dir=tmp_path,
        discover_replicas=1,
        adjudicate_replicas=3,
        concurrency=8,
        out_root=tmp_path,
        pause=False,
        dynamic_brief=None,
        run_handle=run,
        presentation=presentation,
        discovery_mode=DiscoveryMode.INLINE,
    )
    assert artifacts is not None
    assert len(received) == 1
    assert artifacts.summary is not None
    assert artifacts.summary.synthesis == facts
    assert artifacts.summary.status == summarize_run(run.run_id, discovered).status
    assert run.load_summary().synthesis == facts
    retained = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert retained.synthesis == facts
    assert run.load_synthesis() == (None if fallback else document())
    assert (document().overview in run.load_report()) is not fallback
    reloaded = pipeline.load_pipeline_artifacts(run.run_id, tmp_path, require_outcome=True)
    assert reloaded.synthesis == (None if fallback else document())


@pytest.mark.parametrize("operator_override", [False, True])
def test_report_operator_file_wins_over_retained_synthesis(
    tmp_path: Path,
    operator_override: bool,
) -> None:
    run = RunStore(tmp_path).create(target())
    run.save_target(target())
    run.save_discover(DiscoverResult(lane_results={}, findings=[], coverage=[]))
    run.save_merge(merge([], lane_tiers={}))
    run.save_outcome(outcome())
    run.save_synthesis(document())
    args = ["report", "--run", run.run_id, "--out", str(tmp_path)]
    if operator_override:
        supplied = tmp_path / "operator.md"
        supplied.write_text("Operator-supplied assessment.\n")
        args.extend(["--synthesis", str(supplied)])
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    report = run.load_report()
    assert ("Operator-supplied assessment." in report) is operator_override
    assert (document().overview in report) is not operator_override
    assert run.load_synthesis() == document()


@pytest.mark.parametrize("raw", [None, "{", '{"overview":"wrong shape"}'])
def test_missing_or_invalid_synthesis_is_safe_to_replay(tmp_path: Path, raw: str | None) -> None:
    run = RunStore(tmp_path).create(target())
    if raw is not None:
        (run.dir / "synthesis.json").write_text(raw)
    assert run.load_synthesis() is None


def test_synthesis_facts_survive_summary_serialization_and_legacy_load() -> None:
    facts = SynthesisFacts(
        status="fallback:no_output_after:30s",
        model="configured-model",
        reasoning_effort="high",
        wall_seconds=30.0,
        tool_calls=0,
    )
    summary = execution_summary(
        DiscoverResult(lane_results={}, findings=[], coverage=[]),
        merge([], lane_tiers={}),
        outcome(),
        [],
        synthesis=facts,
    )
    encoded = json.loads(summary.model_dump_json())
    assert encoded["synthesis"] == facts.model_dump(mode="json")
    assert ExecutionSummary.model_validate(encoded).synthesis == facts
    del encoded["synthesis"]
    assert ExecutionSummary.model_validate(encoded).synthesis.status == "fallback:not-run"


async def test_skipped_adjudication_records_unavailable_synthesis_without_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    discovered = DiscoverResult(lane_results={}, findings=[], coverage=[])

    async def discover(**_: object) -> DiscoverResult:
        return discovered

    async def forbidden(**_: object):
        pytest.fail("synthesis ran without adjudication evidence")

    monkeypatch.setattr(pipeline, "discover", discover)
    monkeypatch.setattr(pipeline, "synthesize", forbidden)
    unused: Any = None
    artifacts = await pipeline.execute_pipeline(
        registry=unused,
        lanes_root=tmp_path,
        target=target(),
        active_lanes=[],
        runtime=unused,
        adjudicator=unused,
        repo_dir=None,
        discover_replicas=1,
        adjudicate_replicas=1,
        concurrency=1,
        out_root=tmp_path,
        pause=False,
        dynamic_brief=None,
        discovery_mode=DiscoveryMode.INLINE,
    )
    assert artifacts is not None
    retained = ExecutionSummary.model_validate_json(
        (artifacts.run.dir / "summary.json").read_text()
    )
    assert retained.synthesis.status == "fallback:not-run"
    assert artifacts.synthesis is None


async def test_disabled_synthesis_skips_runtime_records_status_and_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    discovered = DiscoverResult(lane_results={}, findings=[], coverage=[])

    async def discover(**_: object) -> DiscoverResult:
        return discovered

    async def adjudicate(*_: object, **__: object) -> AdjudicationOutcome:
        return outcome()

    async def forbidden(**_: object):
        pytest.fail("disabled synthesis invoked runtime")

    monkeypatch.setattr(pipeline, "discover", discover)
    monkeypatch.setattr(pipeline, "synthesize", forbidden)
    presentation = PresentationConfig(synthesis=SynthesisConfig(enabled=False))
    unused: Any = None
    artifacts = await pipeline.execute_pipeline(
        registry=unused,
        lanes_root=tmp_path,
        target=target(),
        active_lanes=[],
        runtime=unused,
        adjudicator=adjudicate,
        repo_dir=tmp_path,
        discover_replicas=1,
        adjudicate_replicas=1,
        concurrency=1,
        out_root=tmp_path,
        pause=False,
        dynamic_brief=None,
        presentation=presentation,
        discovery_mode=DiscoveryMode.INLINE,
    )
    assert artifacts is not None
    assert artifacts.synthesis is None
    assert artifacts.summary is not None
    assert artifacts.summary.synthesis.status == "disabled"
