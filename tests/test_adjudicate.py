from __future__ import annotations

import inspect
import runpy
import shutil
import subprocess
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest

import rvw.adjudicate as adjudicate_module
from rvw.adjudicate import (
    AdjudicationInfrastructureError,
    AdjudicationOutcome,
    adjudicate,
    adjudication_schema,
    build_adjudication_prompt,
)
from rvw.diffbudget import apply_diff_budget
from rvw.hostslots import HostSlotGate
from rvw.merge import CollapseGroup, MergeResult
from rvw.runtimes import RunResult, RunStatus
from rvw.runtimes.codex import CodexRuntime
from rvw.schema import RuntimeAdjudication, RuntimeAdjudicationItem, Severity, Verdict
from rvw.target import ResolvedTarget

FIXTURES = Path(__file__).parent / "fixtures"


def diff_segment(path: str, body: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+{body}\n"


def make_group(key: str, *, body: str | None = None, line: int = 8) -> CollapseGroup:
    return CollapseGroup(
        key=key,
        rule_id="unscoped/correctness",
        file="deep.ts",
        hunk_id="deep.ts:1",
        line=line,
        severity=Severity.WARNING,
        lane_ids=["base/unscoped-sweep"],
        agreement=1,
        bodies=[body or f"candidate body for {key}"],
        anchorable=True,
        findings=[],
        priority=[0, 1, 0, 2],
    )


def make_merged(*groups: CollapseGroup) -> MergeResult:
    return MergeResult(groups=list(groups), sites=[], pattern_folds=[], region_folds=[])


def make_target(diff: str | None = None) -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
        repo="owner/repo",
        base_sha="0" * 40,
        head_sha="1" * 40,
        changed_paths=["deep.ts"],
        diff=diff if diff is not None else diff_segment("deep.ts", "new"),
    )


def item(
    key: str,
    verdict: Verdict,
    reason: str | None = None,
    evidence: str | None = None,
) -> RuntimeAdjudicationItem:
    return RuntimeAdjudicationItem(
        group_key=key,
        verdict=verdict,
        reason=reason or f"{verdict.value} reason for {key}",
        evidence=evidence if evidence is not None else f"source quote for {key}",
    )


class FakeRuntime:
    name = "fake"

    def __init__(self, waves: Sequence[Sequence[RuntimeAdjudication | None]]) -> None:
        self._responses = [response for wave in waves for response in wave]
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
        response = self._responses[len(self.calls)]
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
                lane_id="adjudicate",
                replica=replica,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="scripted-invalid",
                wall_seconds=0,
                artifact_dir=run_dir,
            )
        return RunResult(
            lane_id="adjudicate",
            replica=replica,
            status=RunStatus.VALID,
            output=response,
            invalid_reason=None,
            wall_seconds=0,
            artifact_dir=run_dir,
        )

    async def execute(self, **kwargs: object) -> RunResult:
        raise AssertionError(f"lane execute must not be called: {kwargs}")


async def run_fake(
    tmp_path: Path,
    groups: Sequence[CollapseGroup],
    waves: Sequence[Sequence[RuntimeAdjudication | None]],
    *,
    replicas: int = 3,
    deadline_seconds: int = 30,
) -> tuple[AdjudicationOutcome, FakeRuntime]:
    runtime = FakeRuntime(waves)
    outcome = await adjudicate(
        make_merged(*groups),
        target=make_target(),
        runtime=runtime,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
        replicas=replicas,
        deadline_seconds=deadline_seconds,
        concurrency=2,
    )
    return outcome, runtime


def test_adjudicate_defaults_to_three_replicas() -> None:
    assert inspect.signature(adjudicate).parameters["replicas"].default == 3


async def test_explicit_single_replica_uses_single_vote(tmp_path: Path) -> None:
    group = make_group("single-vote")
    wave = [RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="safe")])]

    outcome, runtime = await run_fake(tmp_path, [group], [wave], replicas=1)

    assert outcome.verdicts[group.key] is Verdict.REJECTED
    assert outcome.replica_votes[group.key] == [Verdict.REJECTED]
    assert len(runtime.calls) == 1


async def test_adjudicate_propagates_injected_host_gate_to_every_runtime_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    group = make_group("gated")
    response = RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)])
    runtime = FakeRuntime([[response, response]])
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")
    seen: list[HostSlotGate | None] = []

    @asynccontextmanager
    async def recording_host_slot(received: HostSlotGate | None) -> AsyncIterator[None]:
        seen.append(received)
        yield

    monkeypatch.setattr(adjudicate_module, "host_slot", recording_host_slot)

    await adjudicate(
        make_merged(group),
        target=make_target(),
        runtime=runtime,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
        replicas=2,
        host_gate=gate,
    )

    assert len(runtime.calls) == 2
    assert seen == [gate, gate]


async def test_majority_confirmed_and_rejected(tmp_path: Path) -> None:
    confirmed = make_group("confirmed")
    rejected = make_group("rejected")
    wave = [
        RuntimeAdjudication(
            items=[
                item(confirmed.key, Verdict.CONFIRMED, "first confirmed", "bad_call()"),
                item(rejected.key, Verdict.REJECTED, "first rejected", "safe_call()"),
            ]
        ),
        RuntimeAdjudication(
            items=[
                item(confirmed.key, Verdict.CONFIRMED),
                item(rejected.key, Verdict.REJECTED),
            ]
        ),
        RuntimeAdjudication(
            items=[
                item(confirmed.key, Verdict.REJECTED),
                item(rejected.key, Verdict.CONFIRMED),
            ]
        ),
    ]

    outcome, runtime = await run_fake(tmp_path, [confirmed, rejected], [wave])

    assert outcome.verdicts == {
        confirmed.key: Verdict.CONFIRMED,
        rejected.key: Verdict.REJECTED,
    }
    assert outcome.reasons == {
        confirmed.key: "first confirmed",
        rejected.key: "first rejected",
    }
    assert outcome.evidence == {confirmed.key: "bad_call()", rejected.key: "safe_call()"}
    assert outcome.replica_votes[confirmed.key] == [
        Verdict.CONFIRMED,
        Verdict.CONFIRMED,
        Verdict.REJECTED,
    ]
    assert outcome.unresolved == []
    assert all(call["workdir"] == tmp_path for call in runtime.calls)


async def test_missing_items_vote_uncertain_and_only_tied_group_is_expanded(
    tmp_path: Path,
) -> None:
    decided = make_group("decided", body="DECIDED BODY")
    tied = make_group("tied", body="TIED BODY")
    initial = [
        RuntimeAdjudication(
            items=[item(decided.key, Verdict.CONFIRMED), item(tied.key, Verdict.CONFIRMED)]
        ),
        RuntimeAdjudication(items=[item(decided.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(tied.key, Verdict.REJECTED, evidence="not broken")]),
    ]
    expanded = [
        RuntimeAdjudication(items=[item(tied.key, Verdict.CONFIRMED, "expanded wins")]),
        RuntimeAdjudication(items=[item(tied.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(tied.key, Verdict.REJECTED, evidence="counter")]),
    ]

    outcome, runtime = await run_fake(
        tmp_path, [decided, tied], [initial, expanded], deadline_seconds=25
    )

    assert outcome.verdicts == {
        decided.key: Verdict.CONFIRMED,
        tied.key: Verdict.CONFIRMED,
    }
    assert outcome.replica_votes[decided.key] == [
        Verdict.CONFIRMED,
        Verdict.CONFIRMED,
        Verdict.UNCERTAIN,
    ]
    assert outcome.replica_votes[tied.key] == [
        Verdict.CONFIRMED,
        Verdict.CONFIRMED,
        Verdict.REJECTED,
    ]
    assert outcome.reasons[tied.key] == "expanded wins"
    assert len(runtime.calls) == 6
    expanded_calls = runtime.calls[3:]
    assert all(call["deadline_seconds"] == 50 for call in expanded_calls)
    assert all("EXPANDED CONTEXT PASS" in cast(str, call["prompt"]) for call in expanded_calls)
    assert all("TIED BODY" in cast(str, call["prompt"]) for call in expanded_calls)
    assert all("DECIDED BODY" not in cast(str, call["prompt"]) for call in expanded_calls)


async def test_expanded_uncertainty_uses_distinct_agentic_runtime(tmp_path: Path) -> None:
    group = make_group("needs-source")
    initial = FakeRuntime(
        [
            [
                RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
                RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="counter")]),
                RuntimeAdjudication(items=[item(group.key, Verdict.UNCERTAIN, evidence="")]),
            ]
        ]
    )
    expanded = FakeRuntime(
        [
            [
                RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
                RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
                RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="counter")]),
            ]
        ]
    )

    outcome = await adjudicate(
        make_merged(group),
        target=make_target(),
        runtime=initial,
        expanded_runtime=expanded,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
    )

    assert outcome.verdicts[group.key] is Verdict.CONFIRMED
    assert len(initial.calls) == 3
    assert len(expanded.calls) == 3
    assert all("## Evidence boundary" in cast(str, call["prompt"]) for call in initial.calls)
    assert all(
        "ACTUAL SOURCE in this working directory" not in cast(str, call["prompt"])
        for call in initial.calls
    )
    assert all("EXPANDED CONTEXT PASS" in cast(str, call["prompt"]) for call in expanded.calls)


async def test_still_uncertain_after_expansion_is_unresolved(tmp_path: Path) -> None:
    group = make_group("uncertain")
    split = [
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="safe")]),
        RuntimeAdjudication(items=[item(group.key, Verdict.UNCERTAIN, evidence="")]),
    ]

    outcome, _runtime = await run_fake(tmp_path, [group], [split, split])

    assert outcome.verdicts[group.key] is Verdict.UNCERTAIN
    assert outcome.unresolved == [group.key]


async def test_empty_rejected_evidence_is_coerced(tmp_path: Path) -> None:
    group = make_group("coerced")
    initial = [
        RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="")]),
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
    ]

    outcome, _runtime = await run_fake(tmp_path, [group], [initial])

    assert outcome.verdicts[group.key] is Verdict.CONFIRMED
    assert outcome.replica_votes[group.key][0] is Verdict.UNCERTAIN
    assert outcome.coerced_rejections == 1


async def test_all_invalid_retries_once_before_voting(tmp_path: Path) -> None:
    group = make_group("retry")
    invalid = [None, None, None]
    retry = [
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="safe")]),
    ]

    outcome, runtime = await run_fake(tmp_path, [group], [invalid, retry])

    assert outcome.verdicts[group.key] is Verdict.CONFIRMED
    assert len(runtime.calls) == 6
    assert all("initial-retry" in cast(Path, call["run_dir"]).parts for call in runtime.calls[3:])


async def test_all_invalid_after_retry_is_infrastructure_failure(tmp_path: Path) -> None:
    group = make_group("all-invalid")
    invalid = [None, None, None]
    runtime = FakeRuntime([invalid, invalid])

    with pytest.raises(
        AdjudicationInfrastructureError, match="no valid adjudication output"
    ) as raised:
        await adjudicate(
            make_merged(group),
            target=make_target(),
            runtime=runtime,
            repo_dir=tmp_path,
            out_root=tmp_path / "out",
            replicas=3,
            deadline_seconds=30,
        )

    assert len(runtime.calls) == 6
    assert raised.value.pass_name == "initial"
    assert len(raised.value.attempts) == 6
    assert {attempt.reason for attempt in raised.value.attempts} == {"scripted-invalid"}
    assert raised.value.outcome is None


def test_uncertain_runtime_item_requires_non_empty_reason() -> None:
    with pytest.raises(ValueError, match=r"UNCERTAIN.*reason"):
        RuntimeAdjudicationItem(
            group_key="group",
            verdict=Verdict.UNCERTAIN,
            reason="   ",
            evidence="",
        )


def test_uncertain_outcome_requires_non_empty_reason() -> None:
    with pytest.raises(ValueError, match=r"UNCERTAIN.*reason"):
        AdjudicationOutcome(
            verdicts={"group": Verdict.UNCERTAIN},
            reasons={"group": ""},
            evidence={"group": ""},
            replica_votes={"group": [Verdict.UNCERTAIN]},
            unresolved=["group"],
            coerced_rejections=0,
        )


def test_adjudication_schema_is_strict_and_closes_group_keys() -> None:
    schema = adjudication_schema(["first", "second"])
    item_schema = schema["properties"]["items"]["items"]
    assert item_schema["properties"]["group_key"]["enum"] == ["first", "second"]
    assert item_schema["properties"]["verdict"]["enum"] == [
        "CONFIRMED",
        "REJECTED",
        "UNCERTAIN",
    ]

    def assert_strict(node: object) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if node.get("type") == "object" and isinstance(props, dict):
                assert set(cast(list[str], node.get("required", []))) == set(props)
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)


def test_prompt_contract_and_expanded_section() -> None:
    group = make_group("prompt", body="Body one.\nBody two.")

    ordinary = build_adjudication_prompt([group], diff="DIFF BODY", expanded=False)
    expanded = build_adjudication_prompt([group], diff="DIFF BODY", expanded=True)

    assert "You are an adjudicator, not a reviewer." in ordinary
    assert "Do not report new findings." in ordinary
    assert "Body one.\nBody two." in ordinary
    assert "DIFF BODY" in ordinary
    assert "EXPANDED CONTEXT PASS" not in ordinary
    assert "EXPANDED CONTEXT PASS" in expanded


@pytest.mark.live
async def test_adr007_rejects_fabricated_await_and_keeps_genuine_findings(
    tmp_path: Path,
) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    deep_case = runpy.run_path(str(FIXTURES / "adjudicate" / "deep_case.py"))
    candidates = cast(
        tuple[dict[str, object], ...],
        deep_case["CANDIDATES"],
    )
    fabricated_await_key = cast(str, deep_case["FABRICATED_AWAIT_KEY"])
    genuine_catch_key = cast(str, deep_case["GENUINE_CATCH_KEY"])
    genuine_input_key = cast(str, deep_case["GENUINE_INPUT_KEY"])

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    source = (FIXTURES / "deep.ts").read_text(encoding="utf-8")
    (repo_dir / "deep.ts").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "rvw test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "rvw@example.invalid"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "deep.ts"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo_dir, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "show", "HEAD", "--format="],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    groups = [
        make_group(
            cast(str, candidate["key"]),
            body=cast(str, candidate["body"]),
            line=cast(int, candidate["line"]),
        ).model_copy(update={"rule_id": candidate["rule_id"]})
        for candidate in candidates
    ]
    target = ResolvedTarget(
        kind="commit",
        repo="fixture/deep",
        base_sha=None,
        head_sha=head,
        changed_paths=["deep.ts"],
        diff=diff,
    )

    outcome = await adjudicate(
        make_merged(*groups),
        target=target,
        runtime=CodexRuntime(),
        repo_dir=repo_dir,
        out_root=tmp_path / "adjudicate",
        replicas=3,
        deadline_seconds=180,
    )

    assert outcome.verdicts[fabricated_await_key] is Verdict.REJECTED
    assert outcome.evidence[fabricated_await_key]
    assert "await" in outcome.evidence[fabricated_await_key]
    assert outcome.verdicts[genuine_input_key] is Verdict.CONFIRMED
    assert outcome.verdicts[genuine_catch_key] is Verdict.CONFIRMED
    assert genuine_input_key not in outcome.unresolved
    assert genuine_catch_key not in outcome.unresolved


async def test_adjudication_prompt_omits_budget_excluded_content(tmp_path: Path) -> None:
    generated = diff_segment("pnpm-lock.yaml", "generated")
    source = diff_segment("deep.ts", "kept")
    group = make_group("filtered")
    runtime = FakeRuntime([[RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)])]])

    await adjudicate(
        make_merged(group),
        target=make_target(generated + source),
        runtime=runtime,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
        replicas=1,
    )

    prompt = cast(str, runtime.calls[0]["prompt"])
    assert generated not in prompt
    assert source in prompt
    assert "# rvw: 1 files excluded from review diff" in prompt
    assert "pnpm-lock.yaml" in prompt


async def test_adjudication_prompt_diff_equals_the_single_discovery_chunk(
    tmp_path: Path,
) -> None:
    diff = diff_segment("deep.ts", "kept") + diff_segment("other.ts", "also kept")
    chunks, _report = apply_diff_budget(diff)
    group = make_group("byte-parity")
    runtime = FakeRuntime([[RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)])]])

    await adjudicate(
        make_merged(group),
        target=make_target(diff),
        runtime=runtime,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
        replicas=1,
    )

    assert len(chunks) == 1
    prompt = cast(str, runtime.calls[0]["prompt"])
    assert chunks[0].text in prompt


async def test_all_invalid_adjudication_retry_names_prior_invalid_reasons(
    tmp_path: Path,
) -> None:
    group = make_group("retry-feedback")
    runtime = FakeRuntime(
        [
            [None, None],
            [RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]), None],
        ]
    )

    await adjudicate(
        make_merged(group),
        target=make_target(),
        runtime=runtime,
        repo_dir=tmp_path,
        out_root=tmp_path / "out",
        replicas=2,
    )

    assert len(runtime.calls) == 4
    initial_prompts = [cast(str, call["prompt"]) for call in runtime.calls[:2]]
    retry_prompts = [cast(str, call["prompt"]) for call in runtime.calls[2:]]
    for prompt in initial_prompts:
        assert "# Retry feedback" not in prompt
        assert "scripted-invalid" not in prompt
    for prompt in retry_prompts:
        assert "# Retry feedback" in prompt
        assert "replica 1: scripted-invalid" in prompt
        assert "replica 2: scripted-invalid" in prompt
