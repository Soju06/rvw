from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

import rvw.cli as cli_module
import rvw.publish as publish_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import DiscoverResult, DiscoveryPlan, EnrichedFinding
from rvw.discovery_cost import DiscoveryCostError, DiscoveryPreflight
from rvw.merge import merge
from rvw.pipeline import PipelineArtifacts
from rvw.publish import PublishResult
from rvw.runtime_policy import DEFAULT_CODEX_RUNTIME_POLICY
from rvw.schema import Severity, Tier, Verdict
from rvw.stack import (
    FindingLineage,
    Presence,
    PresenceObservation,
    StackManifest,
    StackMember,
)
from rvw.stack_adjudicate import PresenceOutcome
from rvw.stack_store import StackStore
from rvw.store import RunStore
from rvw.summary import CoverageTotals, ReviewStatus, RunSummary
from rvw.target import ResolvedTarget

runner = CliRunner()


def valid_members() -> list[StackMember]:
    first = StackMember(
        repo="owner/repo",
        number=1,
        url="https://github.com/owner/repo/pull/1",
        title="PR 1",
        body="Body 1",
        state="open",
        merged=False,
        base_ref="main",
        base_sha="0" * 40,
        head_ref="stack-1",
        head_sha="1" * 40,
    )
    second = first.model_copy(
        update={
            "number": 2,
            "url": "https://github.com/owner/repo/pull/2",
            "title": "PR 2",
            "body": "Body 2",
            "base_ref": first.head_ref,
            "base_sha": first.head_sha,
            "head_ref": "stack-2",
            "head_sha": "2" * 40,
        }
    )
    third = second.model_copy(
        update={
            "number": 3,
            "url": "https://github.com/owner/repo/pull/3",
            "title": "PR 3",
            "body": "Body 3",
            "base_ref": second.head_ref,
            "base_sha": second.head_sha,
            "head_ref": "stack-3",
            "head_sha": "3" * 40,
        }
    )
    return [first, second, third]


def non_monotonic_members() -> list[StackMember]:
    parent = valid_members()[0].model_copy(
        update={
            "number": 20,
            "url": "https://github.com/owner/repo/pull/20",
            "title": "PR 20",
            "body": "Body 20",
            "head_ref": "stack-parent",
        }
    )
    child = parent.model_copy(
        update={
            "number": 15,
            "url": "https://github.com/owner/repo/pull/15",
            "title": "PR 15",
            "body": "Body 15",
            "base_ref": parent.head_ref,
            "base_sha": parent.head_sha,
            "head_ref": "stack-child",
            "head_sha": "2" * 40,
        }
    )
    return [parent, child]


def target_for(
    number: int,
    *,
    members: list[StackMember] | None = None,
) -> ResolvedTarget:
    members = members or valid_members()
    member = next(item for item in members if item.number == number)
    return ResolvedTarget(
        kind="pr",
        repo=member.repo,
        base_sha=member.base_sha,
        head_sha=member.head_sha,
        changed_paths=["src/a.py"],
        diff="diff --git a/src/a.py b/src/a.py\n",
        pr_number=number,
        pr_title=member.title,
        pr_body=member.body,
    )


def preflight_payload(
    *,
    lanes: int,
    replicas: int,
    chunks: int,
    initial_runs: int,
) -> dict[str, object]:
    retry_upper_bound = initial_runs * 2
    reasons: list[str] = []
    if replicas >= 2:
        reasons.append(f"discovery_replicas={replicas}")
    if retry_upper_bound > 12:
        reasons.append(f"retry_upper_bound={retry_upper_bound} exceeds max_discovery_runs=12")
    reasons.append("reasoning_effort=max")
    return DiscoveryPreflight(
        lanes=lanes,
        replicas=replicas,
        chunks=chunks,
        initial_runs=initial_runs,
        retry_upper_bound=retry_upper_bound,
        initial_prompt_characters=initial_runs,
        max_discovery_runs=12,
        runtime_policy=DEFAULT_CODEX_RUNTIME_POLICY,
        heavy_discovery_reasons=tuple(reasons),
    ).payload()


def stack_discovery_plan(
    members: list[StackMember], preflight: dict[str, object]
) -> cli_module._StackDiscoveryPlan:
    return cli_module._StackDiscoveryPlan(
        member_plans=tuple(
            cli_module._StackMemberDiscoveryPlan(
                member=member,
                target=target_for(member.number, members=members),
                plan=cast(DiscoveryPlan, object()),
            )
            for member in members
        ),
        preflight=preflight,
    )


def pipeline_artifacts(
    out_root: Path,
    number: int,
    *,
    members: list[StackMember] | None = None,
    finding_pr: int = 1,
    status: ReviewStatus = ReviewStatus.COMPLETE,
) -> PipelineArtifacts:
    target = target_for(number, members=members)
    run = RunStore(out_root).create(target)
    findings = (
        [
            EnrichedFinding(
                rule_id="bug/correctness",
                file="src/a.py",
                hunk_id="src/a.py@@-1+1@@",
                line=1,
                severity=Severity.WARNING,
                body="The cache remains stale.",
                anchorable=True,
                lane_id="lane-a",
                replica=1,
            )
        ]
        if number == finding_pr
        else []
    )
    discovered = DiscoverResult(lane_results={}, findings=findings, coverage=[], budget=None)
    merged = merge(findings, lane_tiers={"lane-a": Tier.BASE})
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
        reasons={group.key: "confirmed" for group in merged.groups},
        evidence={group.key: "return stale" for group in merged.groups},
        replica_votes={group.key: [Verdict.CONFIRMED] for group in merged.groups},
        unresolved=[],
        coerced_rejections=0,
    )
    summary = RunSummary(
        run_id=run.run_id,
        status=status,
        failed_lanes=[],
        skipped_lanes=[],
        coverage_totals=CoverageTotals(dispatched=0, valid=0, findings=len(findings)),
        error=None,
    )
    return PipelineArtifacts(
        run=run,
        target=target,
        discovered=discovered,
        merged=merged,
        outcome=outcome,
        report_md=f"# report for {number}\n",
        report_path=run.dir / "report.md",
        summary=summary,
    )


def prepare_complete_stack(out_root: Path) -> tuple[str, Path]:
    handle = StackStore(out_root).create([1, 2, 3])
    handle.save_manifest(
        StackManifest(run_id=handle.run_id, repo="owner/repo", members=valid_members())
    )
    handle.save_member_runs(
        [
            cli_module.MemberRunRef(
                pr_number=number,
                run_id=f"rvw-member-{number}",
                report_path=f"/tmp/rvw/rvw-member-{number}/report.md",
                verdict_counts={"CONFIRMED": 0, "REJECTED": 0, "UNCERTAIN": 0},
            )
            for number in (1, 2, 3)
        ]
    )
    handle.save_lineages([])
    handle.save_report("# completed stack report\n")
    return handle.run_id, handle.dir


def test_stack_plan_writes_manifest_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli_module,
        "resolve_stack",
        lambda numbers, **kwargs: valid_members(),
    )

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "plan",
            "--prs",
            "1,2,3",
            "--out",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["repo"] == "owner/repo"
    assert payload["prs"] == [1, 2, 3]
    manifest = StackStore(tmp_path).open(payload["run_id"]).load_manifest()
    assert [item.number for item in manifest.members] == [1, 2, 3]


def test_stack_review_forwards_split_replica_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_stack_review_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli_module, "_stack_review_pipeline", fake_stack_review_pipeline)

    result = runner.invoke(cli_module.app, ["stack", "review", "--prs", "1,2"])

    assert result.exit_code == 0, result.stdout
    assert calls[0]["discover_replicas"] == 1
    assert calls[0]["adjudicate_replicas"] == 3
    assert calls[0]["deadline_seconds"] == 600


def test_stack_review_runs_members_in_order_and_rechecks_older_lineages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolve_calls = 0
    pipeline_calls: list[tuple[int, int, int]] = []
    presence_calls: list[tuple[int, list[str], int]] = []
    pipeline_concurrency: list[int] = []
    presence_concurrency: list[int] = []
    pipeline_deadlines: list[int] = []
    stack_preflight = preflight_payload(lanes=3, replicas=2, chunks=1, initial_runs=6)
    presence_deadlines: list[int] = []

    def fake_resolve(numbers: list[int], **kwargs: object) -> list[StackMember]:
        nonlocal resolve_calls
        del numbers, kwargs
        resolve_calls += 1
        return valid_members()

    def fake_checkout(**kwargs: object) -> Path:
        destination = kwargs["destination"]
        assert isinstance(destination, Path)
        destination.mkdir(parents=True)
        return destination

    async def fake_pipeline(**kwargs: object) -> PipelineArtifacts:
        target = kwargs["resolved_target"]
        assert isinstance(target, ResolvedTarget)
        assert target.pr_number is not None
        assert "planned_discovery" in kwargs
        discover_replicas = kwargs["discover_replicas"]
        adjudicate_replicas = kwargs["adjudicate_replicas"]
        assert isinstance(discover_replicas, int)
        assert isinstance(adjudicate_replicas, int)
        pipeline_calls.append((target.pr_number, discover_replicas, adjudicate_replicas))
        concurrency = kwargs["concurrency"]
        assert isinstance(concurrency, int)
        pipeline_concurrency.append(concurrency)
        deadline_seconds = kwargs["deadline_seconds"]
        assert isinstance(deadline_seconds, int)
        pipeline_deadlines.append(deadline_seconds)
        return pipeline_artifacts(tmp_path, target.pr_number)

    def fake_stack_preflight(**kwargs: object) -> cli_module._StackDiscoveryPlan:
        assert kwargs["members"] == valid_members()
        assert pipeline_calls == []
        return stack_discovery_plan(valid_members(), stack_preflight)

    async def fake_presence(
        lineages: list[FindingLineage], *, pr_number: int, **kwargs: object
    ) -> PresenceOutcome:
        replicas = kwargs["replicas"]
        assert isinstance(replicas, int)
        concurrency = kwargs["concurrency"]
        assert isinstance(concurrency, int)
        presence_concurrency.append(concurrency)
        deadline_seconds = kwargs["deadline_seconds"]
        assert isinstance(deadline_seconds, int)
        presence_deadlines.append(deadline_seconds)
        lineage_ids = [item.lineage_id for item in lineages]
        presence_calls.append((pr_number, lineage_ids, replicas))
        presence = Presence.ABSENT if pr_number == 3 else Presence.PRESENT
        return PresenceOutcome(
            observations={
                lineage_id: PresenceObservation(
                    pr_number=pr_number,
                    presence=presence,
                    reason="checked",
                    evidence="current source",
                    replica_votes=[presence],
                )
                for lineage_id in lineage_ids
            },
            unresolved=[],
            coerced_evidence=0,
        )

    monkeypatch.setattr(cli_module, "resolve_stack", fake_resolve)
    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(
        cli_module,
        "resolved_target_for_member",
        lambda member, **kwargs: target_for(member.number),
    )
    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_pipeline)
    monkeypatch.setattr(cli_module, "adjudicate_presence", fake_presence)
    monkeypatch.setattr(cli_module, "_stack_discovery_preflight", fake_stack_preflight)

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "review",
            "--prs",
            "1,2,3",
            "--registry",
            str(tmp_path / "registry"),
            "--replicas",
            "2",
            "--adjudicate-replicas",
            "1",
            "--concurrency",
            "4",
            "--deadline",
            "1800",
            "--out",
            str(tmp_path / "stack-runs"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert resolve_calls == 2
    assert pipeline_calls == [(1, 2, 1), (2, 2, 1), (3, 2, 1)]
    assert pipeline_concurrency == [4, 4, 4]
    assert pipeline_deadlines == [1800, 1800, 1800]
    assert [(number, replicas) for number, _lineages, replicas in presence_calls] == [
        (2, 1),
        (3, 1),
    ]
    assert all(lineages for _number, lineages, _replicas in presence_calls)
    assert presence_concurrency == [4, 4]
    assert presence_deadlines == [1800, 1800]
    payload = json.loads(result.stdout)
    handle = StackStore(tmp_path / "stack-runs").open(payload["run_id"])
    assert payload["preflight"] == stack_preflight
    assert (
        json.loads((handle.dir / "preflight.json").read_text(encoding="utf-8")) == stack_preflight
    )
    saved = handle.load_lineages()
    assert len(saved) == 1
    assert saved[0].state.value == "FIXED_IN"
    assert saved[0].state_pr == 3


def test_stack_review_accepts_non_monotonic_manifest_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = non_monotonic_members()

    def fake_checkout(**kwargs: object) -> Path:
        destination = kwargs["destination"]
        assert isinstance(destination, Path)
        destination.mkdir(parents=True)
        return destination

    async def fake_pipeline(**kwargs: object) -> PipelineArtifacts:
        target = kwargs["resolved_target"]
        assert isinstance(target, ResolvedTarget)
        assert target.pr_number is not None
        return pipeline_artifacts(
            tmp_path,
            target.pr_number,
            members=members,
            finding_pr=20,
        )

    async def fake_presence(
        lineages: list[FindingLineage],
        *,
        pr_number: int,
        member_order: list[int],
        **kwargs: object,
    ) -> PresenceOutcome:
        del kwargs
        assert member_order == [20, 15]
        return PresenceOutcome(
            observations={
                lineage.lineage_id: PresenceObservation(
                    pr_number=pr_number,
                    presence=Presence.ABSENT,
                    reason="fixed",
                    evidence="current source",
                    replica_votes=[Presence.ABSENT],
                )
                for lineage in lineages
            },
            unresolved=[],
            coerced_evidence=0,
        )

    monkeypatch.setattr(cli_module, "resolve_stack", lambda *args, **kwargs: members)
    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(
        cli_module,
        "resolved_target_for_member",
        lambda member, **kwargs: target_for(member.number, members=members),
    )
    monkeypatch.setattr(cli_module, "_execute_pipeline", fake_pipeline)
    monkeypatch.setattr(cli_module, "adjudicate_presence", fake_presence)
    monkeypatch.setattr(
        cli_module,
        "_stack_discovery_preflight",
        lambda **kwargs: stack_discovery_plan(
            members,
            preflight_payload(lanes=2, replicas=1, chunks=1, initial_runs=2),
        ),
    )

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "review",
            "--prs",
            "20,15",
            "--registry",
            str(tmp_path / "registry"),
            "--out",
            str(tmp_path / "stack-runs"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    saved = StackStore(tmp_path / "stack-runs").open(payload["run_id"]).load_lineages()
    assert [item.pr_number for item in saved[0].observations] == [20, 15]
    assert saved[0].state.value == "FIXED_IN"
    assert saved[0].state_pr == 15


def test_stack_review_announces_run_id_before_member_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = valid_members()[:2]

    def fake_checkout(**kwargs: object) -> Path:
        destination = kwargs["destination"]
        assert isinstance(destination, Path)
        destination.mkdir(parents=True)
        return destination

    async def failed_pipeline(**kwargs: object) -> PipelineArtifacts:
        del kwargs
        raise RuntimeError("scripted member failure")

    monkeypatch.setattr(cli_module, "resolve_stack", lambda *args, **kwargs: members)
    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(
        cli_module,
        "resolved_target_for_member",
        lambda member, **kwargs: target_for(member.number),
    )
    monkeypatch.setattr(cli_module, "_execute_pipeline", failed_pipeline)
    monkeypatch.setattr(
        cli_module,
        "_stack_discovery_preflight",
        lambda **kwargs: stack_discovery_plan(
            members,
            preflight_payload(lanes=2, replicas=1, chunks=1, initial_runs=2),
        ),
    )

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "review",
            "--prs",
            "1,2",
            "--registry",
            str(tmp_path / "registry"),
            "--out",
            str(tmp_path / "stack-runs"),
        ],
    )

    assert result.exit_code == 3
    assert "stack run id: rvw-stack-" in result.stdout
    assert "scripted member failure" in result.stderr


def test_stack_review_rejects_a_degraded_member_before_recording_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = valid_members()[:2]

    def fake_checkout(**kwargs: object) -> Path:
        destination = kwargs["destination"]
        assert isinstance(destination, Path)
        destination.mkdir(parents=True)
        return destination

    async def degraded_pipeline(**kwargs: object) -> PipelineArtifacts:
        target = kwargs["resolved_target"]
        assert isinstance(target, ResolvedTarget)
        assert target.pr_number is not None
        return pipeline_artifacts(
            tmp_path,
            target.pr_number,
            members=members,
            status=ReviewStatus.DEGRADED,
        )

    async def unexpected_presence(*args: object, **kwargs: object) -> PresenceOutcome:
        del args, kwargs
        raise AssertionError("presence recheck must not run after a degraded member")

    monkeypatch.setattr(cli_module, "resolve_stack", lambda *args, **kwargs: members)
    monkeypatch.setattr(cli_module, "provision_checkout", fake_checkout)
    monkeypatch.setattr(
        cli_module,
        "resolved_target_for_member",
        lambda member, **kwargs: target_for(member.number, members=members),
    )
    monkeypatch.setattr(cli_module, "_execute_pipeline", degraded_pipeline)
    monkeypatch.setattr(cli_module, "adjudicate_presence", unexpected_presence)
    monkeypatch.setattr(
        cli_module,
        "_stack_discovery_preflight",
        lambda **kwargs: stack_discovery_plan(
            members,
            preflight_payload(lanes=1, replicas=1, chunks=1, initial_runs=1),
        ),
    )

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "review",
            "--prs",
            "1,2",
            "--out",
            str(tmp_path),
            "--allow-heavy-discovery",
        ],
    )

    assert result.exit_code == 3
    assert "incomplete review status: degraded" in result.stderr
    stack_dir = next(tmp_path.glob("rvw-stack-*"))
    handle = StackStore(tmp_path).open(stack_dir.name)
    assert handle.load_member_runs() == []
    assert not (stack_dir / "stack-report.md").exists()


def test_stack_review_rejection_does_not_create_a_partial_stack_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = valid_members()[:2]
    preflight = DiscoveryPreflight(
        lanes=2,
        replicas=1,
        chunks=1,
        initial_runs=2,
        retry_upper_bound=4,
        initial_prompt_characters=2,
        max_discovery_runs=12,
        runtime_policy=DEFAULT_CODEX_RUNTIME_POLICY,
        heavy_discovery_reasons=("reasoning_effort=max",),
    )

    def reject_for_cost(**kwargs: object) -> cli_module._StackDiscoveryPlan:
        del kwargs
        raise DiscoveryCostError(preflight)

    monkeypatch.setattr(cli_module, "resolve_stack", lambda *args, **kwargs: members)
    monkeypatch.setattr(cli_module, "_stack_discovery_preflight", reject_for_cost)

    result = runner.invoke(
        cli_module.app,
        ["stack", "review", "--prs", "1,2", "--out", str(tmp_path), "--json"],
    )

    assert result.exit_code == cli_module.EXIT_USER_ERROR
    assert json.loads(result.stdout)["error"] == "heavy-discovery-acknowledgement-required"
    assert list(tmp_path.iterdir()) == []


def test_stack_publish_dry_run_has_no_network_or_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, run_dir = prepare_complete_stack(tmp_path)

    def forbidden_resolve(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError(f"dry-run revalidated: {args} {kwargs}")

    def forbidden_run(command: list[str], payload: str) -> str:
        raise AssertionError(f"dry-run published: {command} {payload}")

    monkeypatch.setattr(cli_module, "resolve_stack", forbidden_resolve)
    monkeypatch.setattr(publish_module, "_run", forbidden_run)

    result = runner.invoke(
        cli_module.app,
        ["stack", "publish", "--run", run_id, "--out", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads((run_dir / "publish-payload.json").read_text(encoding="utf-8"))
    assert payload == {
        "body": "# completed stack report\n",
        "commit_id": "3" * 40,
        "event": "COMMENT",
    }


def test_stack_publish_execute_revalidates_before_single_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _run_dir = prepare_complete_stack(tmp_path)
    events: list[str] = []

    def fake_resolve(numbers: list[int], **kwargs: object) -> list[StackMember]:
        del numbers, kwargs
        events.append("resolve")
        return valid_members()

    def fake_verify(manifest: object, current: object) -> None:
        del manifest, current
        events.append("verify")

    def fake_publish(**kwargs: object) -> PublishResult:
        assert kwargs["execute"] is True
        assert kwargs["pr_number"] == 3
        assert kwargs["commit_id"] == "3" * 40
        events.append("publish")
        return PublishResult(
            review_url="https://github.com/owner/repo/pull/3#pullrequestreview-1",
            inline_count=0,
            body_fallback_count=0,
            state="commented",
        )

    monkeypatch.setattr(cli_module, "resolve_stack", fake_resolve)
    monkeypatch.setattr(cli_module, "verify_manifest", fake_verify)
    monkeypatch.setattr(cli_module, "publish_body_review", fake_publish)

    result = runner.invoke(
        cli_module.app,
        [
            "stack",
            "publish",
            "--run",
            run_id,
            "--out",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert events == ["resolve", "verify", "publish"]
