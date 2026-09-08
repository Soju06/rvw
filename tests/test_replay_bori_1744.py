"""Replay of the first production App review (bori#1744, rvw 0.13.0) with the fixes applied.

The measured run: correctness died at the deadline twice and was redispatched a third
time; hygiene hit an upstream capacity error, then the deadline, then was redispatched;
dynamic/goal-parity died once and recovered on retry; contracts, security-exposure, and
ci-integrity completed first time. Thirteen files with one hunk each were uncovered by the
two dead lanes: 26 lane-hunk receipts, 13 distinct regions.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DEAD_BY_TIMEOUT_REASON, DiscoverResult, discover
from rvw.lane import Lane
from rvw.langgate import check_language
from rvw.merge import merge
from rvw.presentation import PresentationConfig
from rvw.publication import render_publication
from rvw.registry import Registry
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.schema import RuntimeLaneOutput, Tier
from rvw.store import RunStore
from rvw.summary import ReviewStatus, execution_summary, summarize_run
from rvw.target import ResolvedTarget

CHANGED_FILES = [
    ".github/CODEOWNERS",
    "docs/rvw-review.md",
    *(
        f".rvw/lanes/{name}.md"
        for name in (
            "connector-copy",
            "mobile-chat-interactions",
            "mobile-navigation",
            "mobile-ui",
            "shared-web-ui",
            "standards-database",
            "standards-deployment",
            "standards-env",
            "tool-authoring",
            "tool-conformance",
            "web-ui",
        )
    ),
]
LANES = {
    "correctness": Tier.BASE,
    "hygiene": Tier.BASE,
    "dynamic/goal-parity": Tier.DYNAMIC,
    "contracts": Tier.BASE,
    "security-exposure": Tier.BASE,
    "ci-integrity": Tier.BASE,
}


@dataclass(frozen=True)
class Scripted:
    status: RunStatus
    wall_seconds: float
    invalid_reason: str | None = None


# usage.json wall_seconds from /tmp/rvw-1744-artifacts, per attempt in execution order.
SCRIPT: dict[str, Sequence[Scripted]] = {
    "correctness": [
        Scripted(RunStatus.INVALID, 600.134, DEAD_BY_TIMEOUT_REASON),
        Scripted(RunStatus.INVALID, 600.082, DEAD_BY_TIMEOUT_REASON),
    ],
    "hygiene": [
        Scripted(RunStatus.INVALID, 104.9, "exit_nonzero:1"),
        Scripted(RunStatus.INVALID, 600.085, DEAD_BY_TIMEOUT_REASON),
    ],
    "dynamic/goal-parity": [
        Scripted(RunStatus.INVALID, 600.06, DEAD_BY_TIMEOUT_REASON),
        Scripted(RunStatus.VALID, 571.2),
    ],
    "contracts": [Scripted(RunStatus.VALID, 188.9)],
    "security-exposure": [Scripted(RunStatus.VALID, 235.7)],
    "ci-integrity": [Scripted(RunStatus.VALID, 101.0)],
}


class ReplayRuntime(Runtime):
    name = "replay"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    async def execute(
        self,
        *,
        lane: Lane,
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
    ) -> RunResult:
        del prompt, deadline_seconds, workdir
        index = sum(lane_id == lane.id for lane_id, _ in self.calls)
        self.calls.append((lane.id, run_dir))
        scripted = SCRIPT[lane.id][index]
        if scripted.status is RunStatus.INVALID:
            return RunResult(
                lane_id=lane.id,
                replica=1,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason=scripted.invalid_reason,
                wall_seconds=scripted.wall_seconds,
                artifact_dir=run_dir,
            )
        return RunResult(
            lane_id=lane.id,
            replica=1,
            status=RunStatus.VALID,
            output=RuntimeLaneOutput(verdict="PASS", covered=list(CHANGED_FILES), findings=[]),
            invalid_reason=None,
            wall_seconds=scripted.wall_seconds,
            artifact_dir=run_dir,
        )


def write_lanes(lanes_root: Path) -> Registry:
    for lane_id, tier in LANES.items():
        relative = lane_id.removeprefix(f"{tier.value}/")
        path = lanes_root / tier.value / f"{relative}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        prefix = lane_id.split("/", maxsplit=1)[0]
        path.write_text(
            "\n".join(
                [
                    "---",
                    f"lane: {lane_id}",
                    f"tier: {tier.value}",
                    "schedule_hint: normal",
                    "rules:",
                    f"  - {prefix}/rule",
                    "---",
                    "",
                    f"Review as {lane_id}.",
                ]
            ),
            encoding="utf-8",
        )
    return Registry.model_validate(
        {
            "layers": [
                {"id": f"layer-{index}", "tier": tier.value, "lanes": [lane_id]}
                for index, (lane_id, tier) in enumerate(LANES.items())
            ]
        }
    )


def target_1744() -> ResolvedTarget:
    diff = "".join(
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        "@@ -0,0 +1,2 @@\n+line one\n+line two\n"
        for path in CHANGED_FILES
    )
    return ResolvedTarget(
        kind="pr",
        repo="fixture/bori",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=list(CHANGED_FILES),
        diff=diff,
        pr_number=1744,
        pr_title="Add rvw lanes",
        pr_body="Lane documents for the review App.",
    )


async def replay(tmp_path: Path) -> tuple[DiscoverResult, ReplayRuntime]:
    lanes_root = tmp_path / "lanes"
    registry = write_lanes(lanes_root)
    runtime = ReplayRuntime()
    discovered = await discover(
        registry=registry,
        lanes_root=lanes_root,
        target=target_1744(),
        runtime=runtime,
        out_root=tmp_path / "discover-runtime",
        repo_dir=tmp_path,
        deadline_seconds=600,
        locale="ko",
    )
    return discovered, runtime


def outcome_1744() -> AdjudicationOutcome:
    # No findings survive in this replay; only the initial adjudication wave ran (600.144 s).
    return AdjudicationOutcome(
        verdicts={},
        reasons={},
        evidence={},
        replica_votes={},
        unresolved=[],
        coerced_rejections=0,
        wave_wall_seconds={"initial": 600.144},
    )


async def test_dead_lanes_are_not_redispatched_and_the_skip_is_recorded(tmp_path: Path) -> None:
    discovered, runtime = await replay(tmp_path)

    # 6 initial + 3 retries; the third 600 s wave for correctness and hygiene no longer exists.
    assert len(runtime.calls) == 9
    assert [lane_id for lane_id, _ in runtime.calls].count("correctness") == 2
    assert [lane_id for lane_id, _ in runtime.calls].count("hygiene") == 2
    assert not any("coverage-redispatch" in run_dir.parts for _, run_dir in runtime.calls)

    coverage = {lane.lane_id: lane for lane in discovered.coverage}
    for lane_id in ("correctness", "hygiene"):
        assert coverage[lane_id].valid == 0
        assert coverage[lane_id].coverage_redispatched is False
        assert coverage[lane_id].redispatch_skipped == "dead_by_timeout"
        assert coverage[lane_id].redispatch == []
        assert len(coverage[lane_id].uncovered) == 13
    assert coverage["dynamic/goal-parity"].valid == 1
    assert coverage["dynamic/goal-parity"].redispatch_skipped is None
    assert coverage["dynamic/goal-parity"].uncovered == []
    assert all(
        coverage[lane].valid == 1 for lane in ("contracts", "security-exposure", "ci-integrity")
    )


async def test_discover_json_attempts_carry_wave_and_wall_seconds(tmp_path: Path) -> None:
    discovered, _ = await replay(tmp_path)
    run = RunStore(tmp_path / "runs").create(target_1744())
    run.save_discover(discovered)

    persisted = json.loads((run.dir / "discover.json").read_text(encoding="utf-8"))
    coverage = {lane["lane_id"]: lane for lane in persisted["coverage"]}
    assert coverage["correctness"]["runs"][0]["attempts"] == [
        {
            "attempt": 1,
            "wave": "initial",
            "valid": False,
            "invalid_reason": "exit_nonzero:124",
            "wall_seconds": 600.134,
        },
        {
            "attempt": 2,
            "wave": "retry",
            "valid": False,
            "invalid_reason": "exit_nonzero:124",
            "wall_seconds": 600.082,
        },
    ]
    assert coverage["hygiene"]["runs"][0]["attempts"][0]["invalid_reason"] == "exit_nonzero:1"
    assert coverage["hygiene"]["runs"][0]["attempts"][0]["wall_seconds"] == 104.9
    assert coverage["hygiene"]["redispatch_skipped"] == "dead_by_timeout"
    assert coverage["dynamic/goal-parity"]["runs"][0]["attempts"][1] == {
        "attempt": 2,
        "wave": "retry",
        "valid": True,
        "invalid_reason": None,
        "wall_seconds": 571.2,
    }
    assert run.load_discover().coverage == discovered.coverage


async def test_summary_names_failed_lanes_regions_and_the_slowest_waves(tmp_path: Path) -> None:
    discovered, _ = await replay(tmp_path)
    lane_tiers = {lane_id: tier for lane_id, tier in LANES.items()}
    merged = merge(discovered.findings, lane_tiers=lane_tiers)
    summary = execution_summary(
        discovered, merged, outcome_1744(), [], presentation=PresentationConfig(locale="ko")
    )

    assert summarize_run("rvw-replay-pr-1744", discovered).status is ReviewStatus.DEGRADED
    assert [item.lane_id for item in summary.failed_lanes] == ["correctness", "hygiene"]
    assert {item.reason for item in summary.failed_lanes} == {"exit_nonzero:124"}
    assert summary.lanes.model_dump() == {
        "dispatched": 6,
        "valid": 4,
        "uncovered": 26,  # lane_hunk_receipts in the check text
        "uncovered_regions": 13,
    }
    assert summary.wave_wall_seconds.model_dump() == {
        "discovery_initial": 600.134,
        "discovery_retry": 600.085,
        "discovery_redispatch": None,
        "adjudication_initial": 600.144,
        "adjudication_initial_retry": None,
        "adjudication_expanded": None,
        "adjudication_expanded_retry": None,
    }
    assert "검토되지 않은 변경 구간이 13곳 있습니다." in summary.markdown
    assert "검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene." in summary.markdown
    assert check_language(summary.markdown, "ko", protected_literals=["correctness", "hygiene"])

    body = render_publication(
        merged=merged,
        outcome=outcome_1744(),
        coverage=discovered.coverage,
        presentation=PresentationConfig(locale="ko"),
    )
    assert "검토를 완료하지 못한 규칙 묶음 2개: correctness, hygiene." in body
    assert check_language(body, "ko", protected_literals=["correctness", "hygiene"])

    english = execution_summary(
        discovered, merged, outcome_1744(), [], presentation=PresentationConfig(locale="en")
    )
    assert english.markdown.endswith(
        "Changed regions not reviewed: 13. Rule sets that did not finish: 2 (correctness, hygiene)."
    )
    # The serialized contract the Worker consumes carries every fact the check text needs.
    facts = json.loads(summary.model_dump_json())
    assert facts["failed_lanes"] == [
        {"lane_id": "correctness", "reason": "exit_nonzero:124"},
        {"lane_id": "hygiene", "reason": "exit_nonzero:124"},
    ]
    assert facts["lanes"]["uncovered"] == 26 and facts["lanes"]["uncovered_regions"] == 13
