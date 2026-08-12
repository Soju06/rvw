from __future__ import annotations

import inspect
import runpy
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from rvw.adjudicate import (
    AdjudicationOutcome,
    adjudicate,
    adjudication_schema,
    build_adjudication_prompt,
)
from rvw.merge import CollapseGroup, MergeResult
from rvw.runtimes import RunResult, RunStatus
from rvw.runtimes.codex import CodexRuntime
from rvw.schema import RuntimeAdjudication, RuntimeAdjudicationItem, Severity, Verdict
from rvw.target import ResolvedTarget

FIXTURES = Path(__file__).parent / "fixtures"


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


def make_target(diff: str = "@@ -1 +1 @@\n-old\n+new\n") -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
        repo="owner/repo",
        base_sha="0" * 40,
        head_sha="1" * 40,
        changed_paths=["deep.ts"],
        diff=diff,
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


async def test_all_invalid_after_retry_becomes_uncertain_and_expands(tmp_path: Path) -> None:
    group = make_group("all-invalid")
    invalid = [None, None, None]
    split = [
        RuntimeAdjudication(items=[item(group.key, Verdict.CONFIRMED)]),
        RuntimeAdjudication(items=[item(group.key, Verdict.REJECTED, evidence="safe")]),
        RuntimeAdjudication(items=[item(group.key, Verdict.UNCERTAIN, evidence="")]),
    ]

    outcome, runtime = await run_fake(tmp_path, [group], [invalid, invalid, split])

    assert outcome.verdicts[group.key] is Verdict.UNCERTAIN
    assert outcome.unresolved == [group.key]
    assert len(runtime.calls) == 9
    assert all("initial-retry" in cast(Path, call["run_dir"]).parts for call in runtime.calls[3:6])
    assert all("expanded" in cast(Path, call["run_dir"]).parts for call in runtime.calls[6:])


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
