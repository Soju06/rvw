from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

import rvw.discover as discover_module
from rvw.diffbudget import EmptyReviewDiffError
from rvw.discover import (
    DEAD_BY_TIMEOUT_REASON,
    DiscoveryMode,
    RunCoverage,
    covered_hunk_ids,
    dead_by_timeout,
    discover,
    resolve_lane_path,
)
from rvw.dispatch import DEFAULT_DEADLINE_SECONDS, DispatchOutcome, PlannedRun
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.merge import merge
from rvw.registry import Registry
from rvw.runtimes import RunDiagnostic, RunResult, RunStatus, Runtime
from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier
from rvw.target import ResolvedTarget


def write_lane(root: Path, lane_id: str, tier: Tier, *, cost: str = "normal") -> Path:
    relative_id = lane_id.removeprefix(f"{tier.value}/")
    path = root / tier.value / f"{relative_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = lane_id.split("/", maxsplit=1)[0]
    path.write_text(
        "\n".join(
            [
                "---",
                f"lane: {lane_id}",
                f"tier: {tier.value}",
                f"cost: {cost}",
                "rules:",
                f"  - {prefix}/rule",
                "---",
                "",
                f"Review as {lane_id}.",
            ]
        ),
        encoding="utf-8",
    )
    return path


def target(*, pr: bool = False) -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr" if pr else "commit",
        repo="fixture/local",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py"],
        diff=(
            "diff --git a/src/a.py b/src/a.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/a.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+one = 1\n"
            "+two = 2\n"
        ),
        pr_number=12 if pr else None,
        pr_title="Add a thing" if pr else None,
        pr_body="It should stay correct." if pr else None,
    )


class FakeRuntime(Runtime):
    name = "fake"

    def __init__(
        self,
        *,
        findings: dict[str, list[RuntimeFinding]] | None = None,
        invalid_lanes: set[str] | None = None,
        statuses: dict[str, Sequence[RunStatus]] | None = None,
        invalid_reasons: dict[str, Sequence[str]] | None = None,
        covered: dict[str, Sequence[list[str]]] | None = None,
    ) -> None:
        self.findings = findings or {}
        self.invalid_lanes = invalid_lanes or set()
        self.statuses = statuses or {}
        self.invalid_reasons = invalid_reasons or {}
        self.covered = covered or {}
        self.prompts: list[tuple[str, str]] = []
        self.calls: list[tuple[str, int]] = []
        self.run_dirs: list[Path] = []

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
    ) -> RunResult:
        del deadline_seconds, workdir
        replica = int(run_dir.name.removeprefix("r"))
        self.prompts.append((lane.id, prompt))
        self.calls.append((lane.id, replica))
        self.run_dirs.append(run_dir)
        call_index = sum(call_lane == lane.id for call_lane, _replica in self.calls) - 1
        scripted = self.statuses.get(lane.id, ())
        status = (
            scripted[call_index]
            if call_index < len(scripted)
            else RunStatus.INVALID
            if lane.id in self.invalid_lanes
            else RunStatus.VALID
        )
        if status is RunStatus.INVALID:
            reasons = self.invalid_reasons.get(lane.id, ())
            invalid_reason = (
                reasons[call_index] if call_index < len(reasons) else "scripted invalid"
            )
            return RunResult(
                lane_id=lane.id,
                replica=replica,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason=invalid_reason,
                wall_seconds=0,
                artifact_dir=run_dir,
            )
        return RunResult(
            lane_id=lane.id,
            replica=replica,
            status=RunStatus.VALID,
            output=RuntimeLaneOutput(
                verdict="PASS",
                covered=(
                    self.covered[lane.id][call_index]
                    if lane.id in self.covered and call_index < len(self.covered[lane.id])
                    else ["src/a.py"]
                ),
                findings=self.findings.get(lane.id, []),
            ),
            invalid_reason=None,
            wall_seconds=0,
            artifact_dir=run_dir,
        )


def registry(*lane_entries: tuple[str, Tier]) -> Registry:
    return Registry.model_validate(
        {
            "layers": [
                {
                    "id": f"layer-{index}",
                    "tier": tier.value,
                    "lanes": [lane_id],
                }
                for index, (lane_id, tier) in enumerate(lane_entries)
            ]
        }
    )


async def test_discovery_locale_survives_retry_and_coverage_waves(tmp_path: Path) -> None:
    lane_id = "base/locale"
    write_lane(tmp_path / "lanes", lane_id, Tier.BASE)
    runtime = FakeRuntime(
        statuses={lane_id: [RunStatus.INVALID, RunStatus.VALID, RunStatus.VALID]},
        covered={lane_id: [[], [], ["src/a.py"]]},
    )
    await discover(
        registry=registry((lane_id, Tier.BASE)),
        lanes_root=tmp_path / "lanes",
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
        locale="ko",
    )
    assert len(runtime.prompts) == 3
    for _, prompt in runtime.prompts:
        assert (
            "Write every explanatory field (title, body, reason, recommendation) in Korean."
            in prompt
        )
        assert "Do not follow the language of the diff, PR description, or lane text." in prompt


def two_file_target() -> ResolvedTarget:
    first = target().diff
    second = (
        "diff --git a/src/b.py b/src/b.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/b.py\n"
        "@@ -0,0 +10,2 @@\n"
        "+three = 3\n"
        "+four = 4\n"
    )
    return target().model_copy(
        update={"changed_paths": ["src/a.py", "src/b.py"], "diff": first + second}
    )


def test_covered_hunk_ids_accepts_exact_paths_and_intersecting_ranges() -> None:
    hunks = discover_module.parse_hunks(two_file_target().diff)

    assert covered_hunk_ids(hunks, ["src/a.py"]) == {hunks[0].hunk_id}
    assert covered_hunk_ids(hunks, ["src/b.py:10-10"]) == {hunks[1].hunk_id}
    assert covered_hunk_ids(hunks, ["src/b.py:99-100", "malformed:range"]) == set()


async def test_agentic_coverage_redispatches_incomplete_lane_once(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    runtime = FakeRuntime(
        covered={"base-review": [["src/a.py"], ["src/b.py:10-11"]]},
    )

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 2
    assert runtime.run_dirs[-1] == tmp_path / "out" / "coverage-redispatch" / "base-review" / "r1"
    assert result.budget is None
    assert result.coverage[0].coverage_redispatched is True
    assert result.coverage[0].redispatch_skipped is None
    assert result.coverage[0].uncovered == []


async def test_agentic_coverage_skips_redispatch_for_lane_dead_by_timeout(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "correctness", Tier.BASE)
    runtime = FakeRuntime(
        statuses={"correctness": [RunStatus.INVALID, RunStatus.INVALID]},
        invalid_reasons={"correctness": [DEAD_BY_TIMEOUT_REASON, DEAD_BY_TIMEOUT_REASON]},
    )
    expected = [hunk.hunk_id for hunk in discover_module.parse_hunks(two_file_target().diff)]

    result = await discover(
        registry=registry(("correctness", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert runtime.calls == [("correctness", 1), ("correctness", 1)]  # initial + retry only
    assert not any("coverage-redispatch" in run_dir.parts for run_dir in runtime.run_dirs)
    lane = result.coverage[0]
    assert lane.coverage_redispatched is False
    assert lane.redispatch_skipped == "dead_by_timeout"
    assert lane.valid == 0
    assert lane.uncovered == expected
    assert lane.model_dump()["redispatch_skipped"] == "dead_by_timeout"


async def test_agentic_coverage_redispatches_lane_failed_for_non_timeout_reasons(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "hygiene", Tier.BASE)
    runtime = FakeRuntime(
        statuses={"hygiene": [RunStatus.INVALID, RunStatus.INVALID, RunStatus.VALID]},
        invalid_reasons={"hygiene": ["exit_nonzero:1", "exit_nonzero:1"]},
        covered={"hygiene": [[], [], ["src/a.py", "src/b.py"]]},
    )

    result = await discover(
        registry=registry(("hygiene", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 3
    assert runtime.run_dirs[-1] == tmp_path / "out" / "coverage-redispatch" / "hygiene" / "r1"
    assert result.coverage[0].coverage_redispatched is True
    assert result.coverage[0].redispatch_skipped is None
    assert result.coverage[0].uncovered == []


async def test_agentic_coverage_redispatches_lane_recovered_on_retry_but_incomplete(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    runtime = FakeRuntime(
        statuses={"dynamic/goal-parity": [RunStatus.INVALID, RunStatus.VALID, RunStatus.VALID]},
        invalid_reasons={"dynamic/goal-parity": [DEAD_BY_TIMEOUT_REASON]},
        covered={"dynamic/goal-parity": [[], ["src/a.py"], ["src/b.py:10-11"]]},
    )

    result = await discover(
        registry=registry(("dynamic/goal-parity", Tier.DYNAMIC)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 3
    assert result.coverage[0].valid == 1
    assert result.coverage[0].coverage_redispatched is True
    assert result.coverage[0].redispatch_skipped is None
    assert result.coverage[0].uncovered == []


async def test_agentic_coverage_skips_redispatch_after_capacity_error_then_timeout(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "hygiene", Tier.BASE)
    runtime = FakeRuntime(
        statuses={"hygiene": [RunStatus.INVALID, RunStatus.INVALID]},
        invalid_reasons={"hygiene": ["exit_nonzero:1", DEAD_BY_TIMEOUT_REASON]},
    )

    result = await discover(
        registry=registry(("hygiene", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 2
    lane = result.coverage[0]
    assert lane.coverage_redispatched is False
    assert lane.redispatch_skipped == "dead_by_timeout"
    assert [attempt.invalid_reason for attempt in lane.runs[0].attempts] == [
        "exit_nonzero:1",
        DEAD_BY_TIMEOUT_REASON,
    ]


def _final_result(lane_id: str, replica: int, reason: str | None) -> RunResult:
    if reason is None:
        return RunResult(
            lane_id=lane_id,
            replica=replica,
            status=RunStatus.VALID,
            output=RuntimeLaneOutput(verdict="PASS", covered=[], findings=[]),
            invalid_reason=None,
            wall_seconds=1.0,
            artifact_dir=Path(f"/tmp/{lane_id}/r{replica}"),
        )
    return RunResult(
        lane_id=lane_id,
        replica=replica,
        status=RunStatus.INVALID,
        output=None,
        invalid_reason=reason,
        wall_seconds=600.1,
        artifact_dir=Path(f"/tmp/{lane_id}/r{replica}"),
    )


@pytest.mark.parametrize(
    ("final_reasons", "expected"),
    [
        ([DEAD_BY_TIMEOUT_REASON], True),
        ([DEAD_BY_TIMEOUT_REASON, DEAD_BY_TIMEOUT_REASON], True),
        ([DEAD_BY_TIMEOUT_REASON, "exit_nonzero:1"], False),
        (["exit_nonzero:1"], False),
        ([DEAD_BY_TIMEOUT_REASON, None], False),
        ([], False),
    ],
)
def test_dead_by_timeout_requires_every_final_execution_to_be_a_deadline_kill(
    final_reasons: list[str | None], expected: bool
) -> None:
    results = [
        _final_result("lane", replica, reason)
        for replica, reason in enumerate(final_reasons, start=1)
    ]
    assert dead_by_timeout(results) is expected


def test_lane_coverage_rejects_redispatched_and_skipped_together() -> None:
    with pytest.raises(ValueError, match="redispatched and skipped"):
        LaneCoverageModel = discover_module.LaneCoverage
        LaneCoverageModel(
            lane_id="lane",
            dispatched=0,
            valid=0,
            findings=0,
            runs=[],
            coverage_redispatched=True,
            redispatch_skipped="dead_by_timeout",
        )


async def test_agentic_coverage_surfaces_residual_without_third_wave(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    runtime = FakeRuntime(covered={"base-review": [[], []]})
    expected = [hunk.hunk_id for hunk in discover_module.parse_hunks(two_file_target().diff)]

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 2
    assert result.coverage[0].uncovered == expected


async def test_valid_coverage_wave_enriches_findings_after_invalid_runtime_retries(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    finding = RuntimeFinding(
        rule_id="base-review/rule",
        file="src/a.py",
        line=1,
        severity=Severity.WARNING,
        body="Recovered during coverage wave",
    )
    runtime = FakeRuntime(
        findings={"base-review": [finding]},
        statuses={"base-review": [RunStatus.INVALID, RunStatus.INVALID, RunStatus.VALID]},
        covered={"base-review": [[], [], ["src/a.py", "src/b.py"]]},
    )

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=two_file_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        repo_dir=tmp_path,
    )

    assert len(runtime.calls) == 3
    assert len(result.findings) == 1
    assert result.coverage[0].findings == 1
    assert result.coverage[0].runs[0].findings == 0
    assert result.coverage[0].uncovered == []


def test_resolve_lane_path_uses_owning_tier_for_all_shapes(tmp_path: Path) -> None:
    base = write_lane(tmp_path, "slop-hygiene", Tier.BASE)
    scope = write_lane(tmp_path, "frontend/skeleton-parity", Tier.SCOPE)
    dynamic = write_lane(tmp_path, "dynamic/goal-parity", Tier.DYNAMIC)

    assert resolve_lane_path(tmp_path, "slop-hygiene", Tier.BASE) == base
    assert resolve_lane_path(tmp_path, "frontend/skeleton-parity", Tier.SCOPE) == scope
    assert resolve_lane_path(tmp_path, "dynamic/goal-parity", Tier.DYNAMIC) == dynamic


def test_discover_defaults_to_one_replica() -> None:
    assert inspect.signature(discover).parameters["replicas"].default == 1


def test_resolve_lane_path_error_lists_attempted_path(tmp_path: Path) -> None:
    attempted = tmp_path / "scope" / "frontend" / "missing.md"
    with pytest.raises(FileNotFoundError, match=str(attempted)):
        resolve_lane_path(tmp_path, "frontend/missing", Tier.SCOPE)


async def test_lane_filter_and_dispatch_are_applied_in_one_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "slop-hygiene", Tier.BASE)
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    reg = registry(("slop-hygiene", Tier.BASE), ("dynamic/goal-parity", Tier.DYNAMIC))
    runtime = FakeRuntime()
    dispatch_calls = 0
    dispatch_concurrency: list[int] = []
    original_dispatch = discover_module.dispatch_outcome

    async def counting_dispatch(
        runs: Sequence[PlannedRun],
        dispatch_runtime: Runtime,
        *,
        out_root: Path,
        concurrency: int = 8,
        deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
        on_progress: Callable[[RunResult], None] | None = None,
        host_gate: HostSlotGate | None = None,
    ) -> DispatchOutcome:
        nonlocal dispatch_calls
        dispatch_calls += 1
        dispatch_concurrency.append(concurrency)
        return await original_dispatch(
            runs,
            dispatch_runtime,
            out_root=out_root,
            concurrency=concurrency,
            deadline_seconds=deadline_seconds,
            on_progress=on_progress,
            host_gate=host_gate,
        )

    monkeypatch.setattr(discover_module, "dispatch_outcome", counting_dispatch)

    result = await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=2,
        concurrency=3,
        lane_filter=["slop-hygiene"],
        mode=DiscoveryMode.INLINE,
    )

    assert dispatch_calls == 1
    assert dispatch_concurrency == [3]
    assert set(result.lane_results) == {"slop-hygiene"}
    assert runtime.calls == [("slop-hygiene", 1), ("slop-hygiene", 2)]


async def test_pr_brief_fallback_and_operator_brief_wins(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "dynamic/goal-parity", Tier.DYNAMIC)
    reg = registry(("dynamic/goal-parity", Tier.DYNAMIC))

    fallback_runtime = FakeRuntime()
    await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(pr=True),
        runtime=fallback_runtime,
        out_root=tmp_path / "fallback",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )
    fallback_prompt = fallback_runtime.prompts[0][1]
    assert "Add a thing\n\nIt should stay correct." in fallback_prompt
    assert "UNVERIFIED claim of intent" in fallback_prompt

    operator_runtime = FakeRuntime()
    await discover(
        registry=reg,
        lanes_root=lanes_root,
        target=target(pr=True),
        runtime=operator_runtime,
        out_root=tmp_path / "operator",
        brief="Operator-authored intent",
        brief_source="pr_body",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )
    operator_prompt = operator_runtime.prompts[0][1]
    assert "Operator-authored intent" in operator_prompt
    assert "Add a thing" not in operator_prompt
    assert "UNVERIFIED claim of intent" not in operator_prompt


async def test_enrichment_computes_hunks_anchors_and_off_diff_fallback(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    raw_findings = [
        RuntimeFinding(
            rule_id="base-review/rule",
            file="src/a.py",
            line=1,
            severity=Severity.WARNING,
            body="Anchored issue",
        ),
        RuntimeFinding(
            rule_id="base-review/rule",
            file="elsewhere.py",
            line=99,
            severity=Severity.SUGGESTION,
            body="Off-diff issue",
        ),
    ]
    runtime = FakeRuntime(findings={"base-review": raw_findings})

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )

    anchored, off_diff = result.findings
    assert anchored.lane_id == "base-review"
    assert anchored.replica == 1
    assert anchored.hunk_id == "src/a.py@@-0,0+1,2@@"
    assert anchored.anchorable is True
    assert anchored.line == 1
    assert off_diff.hunk_id == "elsewhere.py:*"
    assert off_diff.anchorable is False
    assert off_diff.line == 99


async def test_coverage_keeps_all_invalid_lane(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "good", Tier.BASE)
    write_lane(lanes_root, "bad", Tier.BASE)
    runtime = FakeRuntime(invalid_lanes={"bad"})

    result = await discover(
        registry=registry(("good", Tier.BASE), ("bad", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=2,
        mode=DiscoveryMode.INLINE,
    )

    coverage = {entry.lane_id: entry for entry in result.coverage}
    assert coverage["good"].model_dump() == {
        "lane_id": "good",
        "dispatched": 2,
        "valid": 2,
        "findings": 0,
        "runs": [
            {
                "replica": replica,
                "chunk": 1,
                "valid": True,
                "findings": 0,
                "invalid_reason": None,
                "attempts": [{"attempt": 1, "valid": True, "invalid_reason": None}],
                "diagnostic": None,
            }
            for replica in (1, 2)
        ],
        "coverage_redispatched": False,
        "redispatch_skipped": None,
        "uncovered": [],
    }
    assert coverage["bad"].model_dump() == {
        "lane_id": "bad",
        "dispatched": 2,
        "valid": 0,
        "findings": 0,
        "runs": [
            {
                "replica": replica,
                "chunk": 1,
                "valid": False,
                "findings": 0,
                "invalid_reason": "scripted invalid",
                "attempts": [
                    {
                        "attempt": attempt,
                        "valid": False,
                        "invalid_reason": "scripted invalid",
                    }
                    for attempt in (1, 2)
                ],
                "diagnostic": None,
            }
            for replica in (1, 2)
        ],
        "coverage_redispatched": False,
        "redispatch_skipped": None,
        "uncovered": [],
    }
    assert len(runtime.calls) == 6  # two good + two initial bad + two retry bad


async def test_retried_coverage_preserves_ordered_attempt_status_and_reason(
    tmp_path: Path,
) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "recovers", Tier.BASE)
    runtime = FakeRuntime(
        statuses={"recovers": [RunStatus.INVALID, RunStatus.VALID]},
        invalid_reasons={"recovers": ["exit_nonzero:124"]},
    )

    result = await discover(
        registry=registry(("recovers", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        mode=DiscoveryMode.INLINE,
    )

    run = result.coverage[0].runs[0]
    assert run.valid is True
    assert run.invalid_reason is None
    assert [attempt.model_dump() for attempt in run.attempts] == [
        {"attempt": 1, "valid": False, "invalid_reason": "exit_nonzero:124"},
        {"attempt": 2, "valid": True, "invalid_reason": None},
    ]


async def test_non_retried_coverage_has_one_attempt_mirroring_row(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "steady", Tier.BASE)

    result = await discover(
        registry=registry(("steady", Tier.BASE)),
        lanes_root=lanes_root,
        target=target(),
        runtime=FakeRuntime(),
        out_root=tmp_path / "out",
        mode=DiscoveryMode.INLINE,
    )

    run = result.coverage[0].runs[0]
    assert [attempt.model_dump() for attempt in run.attempts] == [
        {
            "attempt": 1,
            "valid": run.valid,
            "invalid_reason": run.invalid_reason,
        }
    ]


@pytest.mark.parametrize(
    "attempts",
    [
        [
            {"attempt": 2, "valid": False, "invalid_reason": "exit_nonzero:124"},
            {"attempt": 3, "valid": True, "invalid_reason": None},
        ],
        [{"attempt": 1, "valid": False, "invalid_reason": "exit_nonzero:124"}],
    ],
)
def test_run_coverage_rejects_non_sequential_or_finally_mismatched_attempts(
    attempts: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError):
        RunCoverage(
            replica=1,
            chunk=1,
            valid=True,
            findings=0,
            invalid_reason=None,
            attempts=attempts,
        )


def test_run_coverage_accepts_attempts_and_final_diagnostic_together() -> None:
    diagnostic = RunDiagnostic(
        exit_code=124,
        log_path="/tmp/lane/r1/run.log",
        log_bytes=17,
        output_path="/tmp/lane/r1/out.json",
        output_bytes=0,
    )

    coverage = RunCoverage(
        replica=1,
        chunk=1,
        valid=False,
        findings=0,
        invalid_reason="empty",
        attempts=[
            {"attempt": 1, "valid": False, "invalid_reason": "exit_nonzero:124"},
            {"attempt": 2, "valid": False, "invalid_reason": "empty"},
        ],
        diagnostic=diagnostic,
    )

    assert coverage.attempts[0].invalid_reason == "exit_nonzero:124"
    assert coverage.diagnostic == diagnostic


def test_run_coverage_rejects_valid_run_with_diagnostic() -> None:
    with pytest.raises(ValueError, match=r"valid.*diagnostic"):
        RunCoverage(
            replica=1,
            chunk=1,
            valid=True,
            findings=0,
            invalid_reason=None,
            attempts=[{"attempt": 1, "valid": True, "invalid_reason": None}],
            diagnostic=RunDiagnostic(exit_code=0),
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"attempt": 0, "valid": True, "invalid_reason": None},
        {"attempt": 1, "valid": True, "invalid_reason": "unexpected"},
        {"attempt": 1, "valid": False, "invalid_reason": None},
        {"attempt": 1, "valid": False, "invalid_reason": "   "},
        {"attempt": 1, "valid": True, "invalid_reason": None, "extra": "forbidden"},
    ],
)
def test_run_attempt_is_strict_and_enforces_validity_reason_invariant(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        discover_module.RunAttempt.model_validate(raw)


async def test_diff_budget_filters_prompt_but_keeps_full_changed_paths(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    source_diff = target().diff
    generated_path = "runtime-snapshots/contract-graph.json"
    generated_diff = (
        f"diff --git a/{generated_path} b/{generated_path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{generated_path}\n"
        "@@ -0,0 +1 @@\n"
        "+generated\n"
    )
    budget_target = target().model_copy(
        update={
            "changed_paths": ["src/a.py", generated_path],
            "diff": generated_diff + source_diff,
        }
    )
    runtime = FakeRuntime()

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=budget_target,
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )

    prompt = runtime.prompts[0][1]
    assert source_diff in prompt
    assert generated_diff not in prompt
    assert "# rvw: 1 files excluded from review diff" in prompt
    assert budget_target.changed_paths == ["src/a.py", generated_path]
    assert result.budget is not None
    assert result.budget.kept_files == ["src/a.py"]
    assert result.budget.excluded_reason == {generated_path: "generated-path"}


async def test_all_excluded_diff_fails_before_discovery_dispatch(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    generated_path = "runtime-snapshots/contract-graph.json"
    generated_target = target().model_copy(
        update={
            "changed_paths": [generated_path],
            "diff": (
                f"diff --git a/{generated_path} b/{generated_path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{generated_path}\n"
                "@@ -0,0 +1 @@\n"
                "+generated\n"
            ),
        }
    )
    runtime = FakeRuntime()

    with pytest.raises(
        EmptyReviewDiffError,
        match=r"^target produced an empty review diff; excluded: ",
    ) as caught:
        await discover(
            registry=registry(("base-review", Tier.BASE)),
            lanes_root=lanes_root,
            target=generated_target,
            runtime=runtime,
            out_root=tmp_path / "out",
            replicas=1,
            mode=DiscoveryMode.INLINE,
        )

    assert caught.value.error_code == "empty-review-diff"
    assert caught.value.excluded_reason == {generated_path: "generated-path"}
    assert runtime.calls == []
    assert runtime.prompts == []


def multi_chunk_target() -> ResolvedTarget:
    paths = [f"src/chunk-{index}.py" for index in range(3)]
    segments = [
        (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            f"+{'x' * 149_900}\n"
        )
        for path in paths
    ]
    return target().model_copy(update={"changed_paths": paths, "diff": "".join(segments)})


async def test_chunk_prompts_fan_out_with_file_plan_and_artifact_axis(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    runtime = FakeRuntime()

    result = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=multi_chunk_target(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )

    assert result.budget is not None
    assert result.budget.chunk_count == 2
    assert runtime.run_dirs == [
        tmp_path / "out" / "base-review" / "c1" / "r1",
        tmp_path / "out" / "base-review" / "c2" / "r1",
    ]
    assert len(runtime.prompts) == 2
    first_prompt = runtime.prompts[0][1]
    second_prompt = runtime.prompts[1][1]
    for prompt, marker in ((first_prompt, "chunk 1/2"), (second_prompt, "chunk 2/2")):
        assert marker in prompt
        assert "src/chunk-0.py" in prompt
        assert "src/chunk-1.py" in prompt
        assert "src/chunk-2.py" in prompt
    assert "[included] src/chunk-0.py" in first_prompt
    assert "[included] src/chunk-1.py" in first_prompt
    assert "[other] src/chunk-2.py" in first_prompt
    assert "diff --git a/src/chunk-2.py" not in first_prompt
    assert "[other] src/chunk-0.py" in second_prompt
    assert "[included] src/chunk-2.py" in second_prompt
    assert "diff --git a/src/chunk-0.py" not in second_prompt
    coverage = result.coverage[0]
    assert coverage.dispatched == 2
    assert coverage.valid == 2
    assert [(run.replica, run.chunk, run.valid) for run in coverage.runs] == [
        (1, 1, True),
        (1, 2, True),
    ]


async def test_stable_finding_id_does_not_depend_on_chunk_plan(tmp_path: Path) -> None:
    lanes_root = tmp_path / "lanes"
    write_lane(lanes_root, "base-review", Tier.BASE)
    finding = RuntimeFinding(
        rule_id="base-review/rule",
        file="src/chunk-0.py",
        line=1,
        severity=Severity.WARNING,
        body="same site",
    )
    one_chunk_target = multi_chunk_target().model_copy(
        update={
            "changed_paths": ["src/chunk-0.py"],
            "diff": multi_chunk_target().diff.split("diff --git a/src/chunk-1.py", maxsplit=1)[0],
        }
    )

    one = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=one_chunk_target,
        runtime=FakeRuntime(findings={"base-review": [finding]}),
        out_root=tmp_path / "one",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )
    many = await discover(
        registry=registry(("base-review", Tier.BASE)),
        lanes_root=lanes_root,
        target=multi_chunk_target(),
        runtime=FakeRuntime(findings={"base-review": [finding]}),
        out_root=tmp_path / "many",
        replicas=1,
        mode=DiscoveryMode.INLINE,
    )

    one_group = merge(one.findings, lane_tiers={"base-review": Tier.BASE}).groups[0]
    many_group = merge(many.findings, lane_tiers={"base-review": Tier.BASE}).groups[0]
    assert one_group.key == many_group.key
