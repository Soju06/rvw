from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path

import pytest

from rvw.runtimes import RunResult, RunStatus
from rvw.schema import Severity, Verdict
from rvw.stack import (
    FindingLineage,
    LineageState,
    Presence,
    PresenceObservation,
    append_observation,
    make_origin_lineage,
)
from rvw.stack_adjudicate import (
    PresenceOutcome,
    RuntimePresence,
    RuntimePresenceItem,
    adjudicate_presence,
    build_presence_prompt,
    presence_schema,
    validate_presence_output,
)
from rvw.target import ResolvedTarget


def test_presence_adjudication_defaults_to_three_replicas() -> None:
    assert inspect.signature(adjudicate_presence).parameters["replicas"].default == 3


def observation(pr_number: int, presence: Presence) -> PresenceObservation:
    return PresenceObservation(
        pr_number=pr_number,
        presence=presence,
        reason=f"{presence.value} at {pr_number}",
        evidence=f"source at {pr_number}" if presence is not Presence.UNCERTAIN else "",
        replica_votes=[presence],
    )


def lineage(
    origin_pr: int = 1,
    *,
    finding_id: str = "finding-1",
) -> FindingLineage:
    return make_origin_lineage(
        origin_pr=origin_pr,
        origin_run_id="rvw-origin",
        origin_finding_id=finding_id,
        rule_id="bug/correctness",
        file="src/a.py",
        line=8,
        severity=Severity.WARNING,
        bodies=["The result can be stale."],
        origin_verdict=Verdict.CONFIRMED,
        origin_reason="confirmed",
        origin_evidence="return cached",
    )


def target(pr_number: int = 2) -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="1" * 40,
        head_sha="2" * 40,
        changed_paths=["src/a.py"],
        diff="@@ -1 +1 @@\n-old\n+new\n",
        pr_number=pr_number,
    )


def runtime_item(
    lineage_id: str,
    presence: Presence,
    *,
    reason: str = "checked",
    evidence: str = "current source",
) -> RuntimePresenceItem:
    return RuntimePresenceItem(
        lineage_id=lineage_id,
        presence=presence,
        reason=reason,
        evidence=evidence,
    )


def test_presence_schema_and_validation_close_lineage_ids() -> None:
    schema = presence_schema(["L1"])
    item_schema = schema["properties"]["items"]["items"]
    assert item_schema["properties"]["lineage_id"]["enum"] == ["L1"]
    with pytest.raises(ValueError, match="outside"):
        validate_presence_output(
            {
                "items": [
                    {
                        "lineage_id": "foreign",
                        "presence": "PRESENT",
                        "reason": "wrong batch",
                        "evidence": "source",
                    }
                ]
            },
            lineage_ids=["L1"],
        )
    with pytest.raises(ValueError, match="duplicate"):
        validate_presence_output(
            {
                "items": [
                    {
                        "lineage_id": "L1",
                        "presence": "PRESENT",
                        "reason": "first",
                        "evidence": "source",
                    },
                    {
                        "lineage_id": "L1",
                        "presence": "ABSENT",
                        "reason": "conflicting duplicate",
                        "evidence": "other source",
                    },
                ]
            },
            lineage_ids=["L1"],
        )


def test_presence_prompt_uses_batch_local_ids_only() -> None:
    candidate = lineage()

    prompt = build_presence_prompt([candidate], target=target(), expanded=False)

    assert "## Lineage L1" in prompt
    assert "lineage_id: L1" in prompt
    assert candidate.lineage_id not in prompt


class FakeRuntime:
    name = "fake"

    def __init__(self, responses: Sequence[RuntimePresence | None]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def execute_raw(
        self,
        *,
        schema: dict[str, object],
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
        validate: object,
    ) -> RunResult:
        del schema, validate
        response = self.responses[len(self.calls)]
        self.calls.append(
            {
                "prompt": prompt,
                "run_dir": run_dir,
                "deadline_seconds": deadline_seconds,
                "workdir": workdir,
            }
        )
        replica = int(run_dir.name.removeprefix("r"))
        if response is None:
            return RunResult(
                lane_id="stack-presence",
                replica=replica,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="scripted-invalid",
                wall_seconds=0,
                artifact_dir=run_dir,
            )
        return RunResult(
            lane_id="stack-presence",
            replica=replica,
            status=RunStatus.VALID,
            output=response,
            invalid_reason=None,
            wall_seconds=0,
            artifact_dir=run_dir,
        )

    async def execute(self, **kwargs: object) -> RunResult:
        raise AssertionError(f"lane execution is not allowed: {kwargs}")


async def run_presence(
    tmp_path: Path,
    responses: Sequence[RuntimePresence | None],
    *,
    replicas: int = 1,
    deadline_seconds: int = 30,
) -> tuple[PresenceOutcome, FakeRuntime]:
    fake = FakeRuntime(responses)
    outcome = await adjudicate_presence(
        [lineage()],
        pr_number=2,
        member_order=[1, 2],
        target=target(),
        runtime=fake,
        repo_dir=tmp_path,
        out_root=tmp_path / "presence",
        replicas=replicas,
        deadline_seconds=deadline_seconds,
    )
    return outcome, fake


def test_present_present_absent_is_fixed_in_third_pr() -> None:
    current = lineage()
    current = append_observation(current, observation(2, Presence.PRESENT))
    current = append_observation(current, observation(3, Presence.ABSENT))

    assert current.state is LineageState.FIXED_IN
    assert current.state_pr == 3


def test_present_absent_present_is_regressed_in_third_pr() -> None:
    current = lineage()
    current = append_observation(current, observation(2, Presence.ABSENT))
    current = append_observation(current, observation(3, Presence.PRESENT))

    assert current.state is LineageState.REGRESSED_IN
    assert current.state_pr == 3


def test_final_uncertain_never_claims_fixed_or_regressed() -> None:
    current = lineage()
    current = append_observation(current, observation(2, Presence.ABSENT))
    current = append_observation(current, observation(3, Presence.UNCERTAIN))

    assert current.state is LineageState.UNCERTAIN
    assert current.state_pr is None


def test_lineage_observations_follow_manifest_order_not_numeric_pr_order() -> None:
    current = lineage(origin_pr=20)
    current = append_observation(current, observation(15, Presence.ABSENT))

    assert [item.pr_number for item in current.observations] == [20, 15]
    assert current.state is LineageState.FIXED_IN
    assert current.state_pr == 15


async def test_presence_accepts_non_monotonic_manifest_order(tmp_path: Path) -> None:
    candidate = lineage(origin_pr=20)
    fake = FakeRuntime([RuntimePresence(items=[runtime_item("L1", Presence.PRESENT)])])

    outcome = await adjudicate_presence(
        [candidate],
        pr_number=15,
        member_order=[20, 15],
        target=target(pr_number=15),
        runtime=fake,
        repo_dir=tmp_path,
        out_root=tmp_path / "presence",
        replicas=1,
    )

    assert outcome.observations[candidate.lineage_id].pr_number == 15
    assert outcome.observations[candidate.lineage_id].presence is Presence.PRESENT


async def test_presence_maps_batch_local_ids_back_to_persisted_ids(
    tmp_path: Path,
) -> None:
    first = lineage(finding_id="finding-1")
    second = lineage(finding_id="finding-2")
    fake = FakeRuntime(
        [
            RuntimePresence(
                items=[
                    runtime_item("L2", Presence.ABSENT),
                    runtime_item("L1", Presence.PRESENT),
                ]
            )
        ]
    )

    outcome = await adjudicate_presence(
        [first, second],
        pr_number=2,
        member_order=[1, 2],
        target=target(),
        runtime=fake,
        repo_dir=tmp_path,
        out_root=tmp_path / "presence",
        replicas=1,
    )

    assert outcome.observations[first.lineage_id].presence is Presence.PRESENT
    assert outcome.observations[second.lineage_id].presence is Presence.ABSENT
    prompt = str(fake.calls[0]["prompt"])
    assert "lineage_id: L1" in prompt
    assert "lineage_id: L2" in prompt
    assert first.lineage_id not in prompt
    assert second.lineage_id not in prompt


async def test_missing_output_gets_one_expanded_pass(tmp_path: Path) -> None:
    key = lineage().lineage_id
    outcome, runtime = await run_presence(
        tmp_path,
        [
            RuntimePresence(items=[]),
            RuntimePresence(items=[runtime_item("L1", Presence.ABSENT)]),
        ],
    )

    assert outcome.observations[key].presence is Presence.ABSENT
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["deadline_seconds"] == 60
    assert "EXPANDED CONTEXT PASS" in str(runtime.calls[1]["prompt"])


async def test_blank_conclusive_evidence_is_coerced_and_remains_uncertain(
    tmp_path: Path,
) -> None:
    key = lineage().lineage_id
    blank = RuntimePresence(items=[runtime_item("L1", Presence.PRESENT, evidence="  ")])
    uncertain = RuntimePresence(items=[runtime_item("L1", Presence.UNCERTAIN, evidence="")])

    outcome, _runtime = await run_presence(tmp_path, [blank, uncertain])

    assert outcome.observations[key].presence is Presence.UNCERTAIN
    assert outcome.coerced_evidence == 1
    assert outcome.unresolved == [key]


async def test_all_invalid_wave_retries_once_before_expansion(tmp_path: Path) -> None:
    key = lineage().lineage_id
    outcome, runtime = await run_presence(
        tmp_path,
        [
            None,
            RuntimePresence(items=[runtime_item("L1", Presence.PRESENT)]),
        ],
    )

    assert outcome.observations[key].presence is Presence.PRESENT
    assert len(runtime.calls) == 2
    first_run_dir = runtime.calls[0]["run_dir"]
    retry_run_dir = runtime.calls[1]["run_dir"]
    assert isinstance(first_run_dir, Path)
    assert isinstance(retry_run_dir, Path)
    assert first_run_dir.parent.name == "initial"
    assert retry_run_dir.parent.name == "initial-retry"
    assert "scripted-invalid" not in str(runtime.calls[0]["prompt"])
    assert "scripted-invalid" in str(runtime.calls[1]["prompt"])


async def test_presence_uses_strict_majority(tmp_path: Path) -> None:
    key = lineage().lineage_id
    responses = [
        RuntimePresence(items=[runtime_item("L1", Presence.PRESENT, evidence="bad path")]),
        RuntimePresence(items=[runtime_item("L1", Presence.PRESENT, evidence="bad path")]),
        RuntimePresence(items=[runtime_item("L1", Presence.ABSENT, evidence="safe path")]),
    ]

    outcome, _runtime = await run_presence(tmp_path, responses, replicas=3)

    assert outcome.observations[key].presence is Presence.PRESENT
    assert outcome.observations[key].replica_votes == [
        Presence.PRESENT,
        Presence.PRESENT,
        Presence.ABSENT,
    ]
