from __future__ import annotations

import json
import subprocess
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

import rvw.policy as policy_module
from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding
from rvw.merge import CollapseGroup, MergeResult, merge
from rvw.policy import AutoPolicy, PolicyNotFound, evaluate, load_policy
from rvw.schema import Severity, Tier, Verdict
from rvw.target import ResolvedTarget

FIXTURES = Path(__file__).parent / "fixtures"


def group(key: str, severity: Severity, agreement: int) -> CollapseGroup:
    return CollapseGroup(
        key=key,
        rule_id=f"test/{key}",
        file=f"{key}.py",
        hunk_id=f"{key}.py:1",
        line=1,
        severity=severity,
        lane_ids=["test"],
        agreement=agreement,
        bodies=[key],
        anchorable=True,
        findings=[],
        priority=[0, agreement, 0, 1],
    )


def merged(*groups: CollapseGroup) -> MergeResult:
    return MergeResult(groups=list(groups), sites=[], pattern_folds=[], region_folds=[])


def outcome(
    verdicts: dict[str, Verdict], *, unresolved: list[str] | None = None
) -> AdjudicationOutcome:
    return AdjudicationOutcome(
        verdicts=verdicts,
        reasons={
            key: "fixture uncertainty reason"
            for key, verdict in verdicts.items()
            if verdict is Verdict.UNCERTAIN
        },
        evidence={},
        replica_votes={},
        unresolved=unresolved or [],
        coerced_rejections=0,
    )


def policy(**overrides: object) -> AutoPolicy:
    raw: dict[str, object] = {
        "promote_to_blocker": {
            "agreement_at_least": 2,
            "severity_at_least": "warning",
        },
        "drop": {"agreement_at_most": 1, "severity_at_most": "suggestion"},
        "block_when": {"severity_at_least": "blocker"},
        "publish_state": "comment",
    }
    raw.update(overrides)
    return AutoPolicy.model_validate(raw)


def test_load_policy_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "auto.yaml"
    path.write_text(
        """promote_to_blocker:
  agreement_at_least: 2
  severity_at_least: warning
drop:
  agreement_at_most: 1
  severity_at_most: suggestion
block_when:
  severity_at_least: blocker
publish_state: none
""",
        encoding="utf-8",
    )
    loaded = load_policy(path)
    assert loaded.publish_state == "none"
    assert loaded.block_when.confirmed_only is True
    with pytest.raises(PolicyNotFound, match=str(tmp_path / "missing.yaml")):
        load_policy(tmp_path / "missing.yaml")


def test_policy_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        policy(extra_setting=True)


def test_drop_uses_original_severity_and_agreement() -> None:
    dropped = group("dropped", Severity.SUGGESTION, 1)
    kept = group("kept", Severity.WARNING, 1)
    result = evaluate(
        policy(),
        merged(dropped, kept),
        outcome({dropped.key: Verdict.CONFIRMED, kept.key: Verdict.CONFIRMED}),
    )
    assert result.dropped == ["dropped"]
    assert result.considered == 1


def test_promote_then_block() -> None:
    promoted = group("promoted", Severity.WARNING, 2)
    result = evaluate(policy(), merged(promoted), outcome({promoted.key: Verdict.CONFIRMED}))
    assert result.promoted == ["promoted"]
    assert result.blocking == ["promoted"]
    assert result.verdict == "BLOCK"


def test_uncertain_only_blocks_when_confirmed_only_is_false() -> None:
    blocker = group("blocker", Severity.BLOCKER, 1)
    default_result = evaluate(policy(), merged(blocker), outcome({}))
    permissive_result = evaluate(
        policy(block_when={"severity_at_least": "blocker", "confirmed_only": False}),
        merged(blocker),
        outcome({blocker.key: Verdict.UNCERTAIN}),
    )
    assert default_result.verdict == "PASS"
    assert default_result.considered == 1
    assert permissive_result.blocking == ["blocker"]


def test_rejected_is_excluded_and_unresolved_is_uncertain() -> None:
    rejected = group("rejected", Severity.BLOCKER, 3)
    unresolved = group("unresolved", Severity.BLOCKER, 3)
    result = evaluate(
        policy(),
        merged(rejected, unresolved),
        outcome(
            {rejected.key: Verdict.REJECTED, unresolved.key: Verdict.CONFIRMED},
            unresolved=[unresolved.key],
        ),
    )
    assert result.verdict == "PASS"
    assert result.considered == 1
    assert result.blocking == []


def real_fixture() -> tuple[MergeResult, AdjudicationOutcome]:
    raw_findings = json.loads((FIXTURES / "smoke_1119_findings.json").read_text(encoding="utf-8"))
    findings = [EnrichedFinding.model_validate(item) for item in raw_findings]
    lane_tiers = {
        finding.lane_id: (Tier.DYNAMIC if finding.lane_id.startswith("dynamic/") else Tier.BASE)
        for finding in findings
    }
    merged_fixture = merge(findings, lane_tiers=lane_tiers)
    raw_outcome = json.loads((FIXTURES / "smoke_1119_outcome.json").read_text(encoding="utf-8"))
    adjudicated = AdjudicationOutcome(
        verdicts={key: Verdict(value) for key, value in raw_outcome["verdicts"].items()},
        reasons=raw_outcome["reasons"],
        evidence=raw_outcome["evidence"],
        replica_votes={
            key: [Verdict(value) for value in votes]
            for key, votes in raw_outcome["replica_votes"].items()
        },
        unresolved=raw_outcome["unresolved"],
        coerced_rejections=raw_outcome["coerced_rejections"],
    )
    return merged_fixture, adjudicated


def test_default_policy_on_real_1119_fixture() -> None:
    merged_fixture, adjudicated = real_fixture()
    result = evaluate(policy(), merged_fixture, adjudicated)
    assert result.verdict == "BLOCK"
    assert result.considered == 13
    assert result.dropped == []
    assert result.promoted == [
        "481b74e181cca5bab3b2e7252c300f8d526b67fd",
        "428ab652ab58581e91e63909766c63f78f14fb2b",
    ]
    assert set(result.blocking) >= {
        "293eeebae652d78e971b9285f9a8548837db9393",
        "caa45924521108ea0d13acdf359734087dd99f58",
        "0679c0ea818933a9a399e8ceb79f45e384429027",
        "7a0b9e94abd6446c02beca0f648b5877dfb2e75a",
        "411f0fa92e9569bcdb4736d14da6389757e63194",
    }


def test_outcome_none_treats_every_group_as_uncertain() -> None:
    merged_fixture, _ = real_fixture()
    result = evaluate(policy(), merged_fixture, None)
    assert result.verdict == "PASS"
    assert result.considered == 13
    assert result.blocking == []


def policy_repo(tmp_path: Path, *, repository_policy: str | None = None) -> ResolvedTarget:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"], cwd=tmp_path, check=True
    )
    (tmp_path / "fixture.txt").write_text("fixture\n", encoding="utf-8")
    if repository_policy is not None:
        path = tmp_path / ".rvw" / "policies" / "auto.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(repository_policy, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=tmp_path, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    return ResolvedTarget(
        kind="pr",
        repo="octo/widgets",
        pr_number=42,
        base_sha=base,
        head_sha="a" * 40,
        changed_paths=["fixture.txt"],
        diff="fixture diff\n",
    )


def test_auto_policy_package_fallback_without_external_registry(tmp_path: Path) -> None:
    target = policy_repo(tmp_path)
    selected = policy_module.resolve_auto_policy(
        target, cwd=tmp_path, external_path=tmp_path / "missing-external.yaml"
    )
    assert selected.source == "package"
    assert selected.path == "rvw:resources/policies/auto-default.yaml"
    assert selected.policy == policy()


def test_auto_policy_explicit_path_wins_over_repository_and_external(tmp_path: Path) -> None:
    target = policy_repo(tmp_path, repository_policy=policy().model_dump_json())
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text(policy(publish_state="none").model_dump_json(), encoding="utf-8")
    external = tmp_path / "external.yaml"
    external.write_text("invalid: external\n", encoding="utf-8")
    selected = policy_module.resolve_auto_policy(
        target, cwd=tmp_path, policy=Path("explicit.yaml"), external_path=external
    )
    assert selected.source == "explicit"
    assert selected.path == str(explicit)
    assert selected.policy.publish_state == "none"


def test_auto_policy_repository_base_wins_over_worktree_and_external(tmp_path: Path) -> None:
    target = policy_repo(tmp_path, repository_policy=policy(publish_state="none").model_dump_json())
    (tmp_path / ".rvw" / "policies" / "auto.yaml").write_text(
        "invalid: untrusted worktree\n", encoding="utf-8"
    )
    external = tmp_path / "external.yaml"
    external.write_text("invalid: external\n", encoding="utf-8")
    with warnings.catch_warnings(record=True) as captured:
        selected = policy_module.resolve_auto_policy(target, cwd=tmp_path, external_path=external)
    assert captured == []
    assert selected.source == "repository"
    assert selected.path == f"{target.base_sha}:.rvw/policies/auto.yaml"
    assert selected.policy.publish_state == "none"


def test_auto_policy_external_fallback_warns_deprecation(tmp_path: Path) -> None:
    target = policy_repo(tmp_path)
    external = tmp_path / "external.yaml"
    external.write_text(policy(publish_state="none").model_dump_json(), encoding="utf-8")
    with pytest.warns(FutureWarning, match="external auto policy.*deprecated"):
        selected = policy_module.resolve_auto_policy(target, cwd=tmp_path, external_path=external)
    assert selected.source == "external"
    assert selected.path == str(external)
    assert selected.policy.publish_state == "none"


def test_auto_policy_missing_explicit_does_not_fall_back(tmp_path: Path) -> None:
    target = policy_repo(tmp_path, repository_policy=policy().model_dump_json())
    with pytest.raises(PolicyNotFound, match=r"missing-explicit\.yaml"):
        policy_module.resolve_auto_policy(target, cwd=tmp_path, policy="missing-explicit.yaml")


@pytest.mark.parametrize("source", ["explicit", "repository", "external"])
def test_auto_policy_malformed_selected_source_does_not_fall_back(
    tmp_path: Path, source: str
) -> None:
    invalid = "invalid: policy\n"
    target = policy_repo(tmp_path, repository_policy=invalid if source == "repository" else None)
    selected_path = tmp_path / "selected.yaml"
    selected_path.write_text(invalid, encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        with pytest.raises(ValidationError):
            policy_module.resolve_auto_policy(
                target,
                cwd=tmp_path,
                policy=selected_path if source == "explicit" else "auto",
                external_path=selected_path,
            )
