"""summary.json exposes failed lanes and per-wave wall time for every adapter."""

from __future__ import annotations

import json

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import (
    AttemptWave,
    DiscoverResult,
    LaneCoverage,
    RedispatchSkip,
    RunAttempt,
    RunCoverage,
)
from rvw.merge import merge
from rvw.presentation import PresentationConfig
from rvw.summary import ExecutionSummary, execution_summary


def attempt(
    number: int, wave: AttemptWave, *, reason: str | None, wall: float | None
) -> RunAttempt:
    return RunAttempt(
        attempt=number,
        wave=wave,
        valid=reason is None,
        invalid_reason=reason,
        wall_seconds=wall,
    )


def run(replica: int, attempts: list[RunAttempt]) -> RunCoverage:
    final = attempts[-1]
    return RunCoverage(
        replica=replica,
        chunk=1,
        valid=final.valid,
        findings=0,
        invalid_reason=final.invalid_reason,
        attempts=attempts,
    )


def lane(
    lane_id: str,
    runs: list[RunCoverage],
    *,
    coverage_redispatched: bool = False,
    redispatch_skipped: RedispatchSkip | None = None,
    redispatch: list[RunAttempt] | None = None,
) -> LaneCoverage:
    return LaneCoverage(
        lane_id=lane_id,
        dispatched=len(runs),
        valid=sum(item.valid for item in runs),
        findings=0,
        runs=runs,
        coverage_redispatched=coverage_redispatched,
        redispatch_skipped=redispatch_skipped,
        redispatch=redispatch or [],
    )


def summary_for(
    coverage: list[LaneCoverage], outcome: AdjudicationOutcome | None
) -> ExecutionSummary:
    discovered = DiscoverResult(lane_results={}, findings=[], coverage=coverage)
    return execution_summary(
        discovered, merge([], lane_tiers={}), outcome, [], presentation=PresentationConfig()
    )


def test_failed_lanes_name_final_reasons_and_skip_valid_lanes() -> None:
    coverage = [
        lane(
            "correctness",
            [
                run(
                    1,
                    [
                        attempt(1, "initial", reason="exit_nonzero:124", wall=600.13),
                        attempt(2, "retry", reason="exit_nonzero:124", wall=600.08),
                    ],
                )
            ],
            redispatch_skipped="dead_by_timeout",
        ),
        lane(
            "hygiene",
            [
                run(
                    1,
                    [
                        attempt(1, "initial", reason="exit_nonzero:1", wall=104.9),
                        attempt(2, "retry", reason="exit_nonzero:124", wall=600.09),
                    ],
                )
            ],
            redispatch_skipped="dead_by_timeout",
        ),
        lane(
            "dynamic/goal-parity",
            [
                run(
                    1,
                    [
                        attempt(1, "initial", reason="exit_nonzero:124", wall=600.06),
                        attempt(2, "retry", reason=None, wall=571.2),
                    ],
                )
            ],
        ),
        lane("contracts", [run(1, [attempt(1, "initial", reason=None, wall=188.9)])]),
    ]

    summary = summary_for(coverage, None)

    assert [item.model_dump() for item in summary.failed_lanes] == [
        {"lane_id": "correctness", "reason": "exit_nonzero:124"},
        {"lane_id": "hygiene", "reason": "exit_nonzero:124"},
    ]
    assert summary.wave_wall_seconds.model_dump() == {
        "discovery_initial": 600.13,
        "discovery_retry": 600.09,
        "discovery_redispatch": None,
        "adjudication_initial": None,
        "adjudication_initial_retry": None,
        "adjudication_expanded": None,
        "adjudication_expanded_retry": None,
    }


def test_differing_final_reasons_within_one_lane_are_joined_in_run_order() -> None:
    coverage = [
        lane(
            "mixed",
            [
                run(1, [attempt(1, "initial", reason="empty", wall=10.0)]),
                run(2, [attempt(1, "initial", reason="schema-invalid", wall=12.0)]),
                run(3, [attempt(1, "initial", reason="empty", wall=11.0)]),
            ],
        )
    ]
    summary = summary_for(coverage, None)
    assert summary.failed_lanes[0].reason == "empty, schema-invalid"


def test_wave_walls_include_redispatch_and_adjudication_waves() -> None:
    coverage = [
        lane(
            "base-review",
            [run(1, [attempt(1, "initial", reason=None, wall=200.0)])],
            coverage_redispatched=True,
            redispatch=[attempt(1, "coverage_redispatch", reason=None, wall=333.3)],
        )
    ]
    outcome = AdjudicationOutcome(
        verdicts={},
        reasons={},
        evidence={},
        replica_votes={},
        unresolved=[],
        coerced_rejections=0,
        wave_wall_seconds={"initial": 600.144, "expanded": 900.5, "expanded-retry": 880.0},
    )
    summary = summary_for(coverage, outcome)
    assert summary.failed_lanes == []
    assert summary.wave_wall_seconds.model_dump() == {
        "discovery_initial": 200.0,
        "discovery_retry": None,
        "discovery_redispatch": 333.3,
        "adjudication_initial": 600.144,
        "adjudication_initial_retry": None,
        "adjudication_expanded": 900.5,
        "adjudication_expanded_retry": 880.0,
    }


def test_attempts_without_wall_time_leave_the_wave_null() -> None:
    coverage = [lane("legacy", [run(1, [attempt(1, "initial", reason=None, wall=None)])])]
    assert summary_for(coverage, None).wave_wall_seconds.discovery_initial is None


def test_legacy_summary_and_outcome_contracts_load_with_defaults() -> None:
    legacy_summary = {
        "schema_version": 1,
        "lanes": {"dispatched": 1, "valid": 1, "uncovered": 0},
        "findings": {"blocker": 0, "warning": 0, "suggestion": 0},
        "verdicts": {"CONFIRMED": 0, "REJECTED": 0, "UNCERTAIN": 0},
        "blockers": [],
        "markdown": "legacy",
    }
    loaded = ExecutionSummary.model_validate_json(json.dumps(legacy_summary))
    assert loaded.failed_lanes == []
    assert loaded.wave_wall_seconds.model_dump() == dict.fromkeys(
        (
            "discovery_initial",
            "discovery_retry",
            "discovery_redispatch",
            "adjudication_initial",
            "adjudication_initial_retry",
            "adjudication_expanded",
            "adjudication_expanded_retry",
        )
    )
    legacy_outcome = {
        "verdicts": {},
        "reasons": {},
        "evidence": {},
        "replica_votes": {},
        "unresolved": [],
        "coerced_rejections": 0,
    }
    assert AdjudicationOutcome.model_validate(legacy_outcome).wave_wall_seconds == {}


def test_outcome_rejects_unknown_wave_labels_and_negative_walls() -> None:
    import pytest

    base = {
        "verdicts": {},
        "reasons": {},
        "evidence": {},
        "replica_votes": {},
        "unresolved": [],
        "coerced_rejections": 0,
    }
    with pytest.raises(ValueError):
        AdjudicationOutcome.model_validate({**base, "wave_wall_seconds": {"third": 1.0}})
    with pytest.raises(ValueError):
        AdjudicationOutcome.model_validate({**base, "wave_wall_seconds": {"initial": -1.0}})
