from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rvw.adjudicate import AdjudicationOutcome
from rvw.discover import EnrichedFinding, LaneCoverage, RunCoverage
from rvw.gate import (
    ACTIONABLE_DISPOSITIONS_PAUSE,
    DispositionDecision,
    DispositionDocument,
    DispositionRecord,
    GateAnchor,
    GateFinding,
    GateInvariantError,
    GatePlan,
    GateVerdict,
    GitHubAuthorizationError,
    InheritanceBlankReason,
    InheritanceSummary,
    InheritanceTier,
    PullRequestState,
    _body_sha256,
    _redact_subprocess_diagnostic,
    build_gate_verdict,
    github_actor_permission,
    load_dispositions,
    load_gate_plan,
    match_inherited_dispositions,
    provision_checkout,
    query_pull_request,
    render_gate_verdict,
    save_gate_plan,
    save_gate_verdict,
    validate_coverage,
    verify_pull_request,
    write_disposition_template,
)
from rvw.merge import MergeResult, merge
from rvw.report import render_report
from rvw.schema import Severity, Tier, Verdict
from rvw.target import ResolvedTarget

HUNK_TEXT = "@@ -1 +1 @@\n-old\n+new\n"
HUNK_DIFF = f"diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n{HUNK_TEXT}"
HUNK_SHA256 = hashlib.sha256(HUNK_TEXT.encode()).hexdigest()


def body_set_sha256(*bodies: str) -> str:
    blocks = (hashlib.sha256(body.encode()).digest() for body in sorted(bodies))
    return hashlib.sha256(b"".join(blocks)).hexdigest()


BODY_SHA256 = body_set_sha256("actionable")


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="pr",
        repo="owner/repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=["src/a.py", "src/b.py", "src/c.py"],
        diff="",
        pr_number=42,
    )


def merged_outcome() -> tuple[MergeResult, AdjudicationOutcome]:
    findings = [
        EnrichedFinding(
            rule_id="rule/blocker",
            file="src/a.py",
            hunk_id="src/a.py@@-1+1@@",
            line=1,
            severity=Severity.BLOCKER,
            body="blocker",
            anchorable=True,
            lane_id="lane-a",
            replica=1,
        ),
        EnrichedFinding(
            rule_id="rule/uncertain",
            file="src/b.py",
            hunk_id="src/b.py@@-1+1@@",
            line=2,
            severity=Severity.WARNING,
            body="uncertain",
            anchorable=True,
            lane_id="lane-b",
            replica=1,
        ),
        EnrichedFinding(
            rule_id="rule/rejected",
            file="src/c.py",
            hunk_id="src/c.py@@-1+1@@",
            line=3,
            severity=Severity.SUGGESTION,
            body="rejected",
            anchorable=True,
            lane_id="lane-c",
            replica=1,
        ),
    ]
    merged = merge(
        findings,
        lane_tiers={"lane-a": Tier.BASE, "lane-b": Tier.BASE, "lane-c": Tier.BASE},
    )
    by_rule = {group.rule_id: group.key for group in merged.groups}
    verdicts = {
        by_rule["rule/blocker"]: Verdict.CONFIRMED,
        by_rule["rule/uncertain"]: Verdict.UNCERTAIN,
        by_rule["rule/rejected"]: Verdict.REJECTED,
    }
    outcome = AdjudicationOutcome(
        verdicts=verdicts,
        reasons={key: verdict.value.lower() for key, verdict in verdicts.items()},
        evidence={key: "evidence" for key in verdicts},
        replica_votes={key: [verdict] * 3 for key, verdict in verdicts.items()},
        unresolved=[by_rule["rule/uncertain"]],
        coerced_rejections=0,
    )
    return merged, outcome


def lane_coverage(
    lane_id: str,
    *,
    replicas: int = 3,
    chunks: int = 1,
    invalid: set[tuple[int, int]] | None = None,
    findings: int = 0,
) -> LaneCoverage:
    invalid = invalid or set()
    runs = [
        RunCoverage(
            replica=replica,
            chunk=chunk,
            valid=(replica, chunk) not in invalid,
            findings=findings if (replica, chunk) == (1, 1) else 0,
            invalid_reason=("scripted_invalid" if (replica, chunk) in invalid else None),
        )
        for chunk in range(1, chunks + 1)
        for replica in range(1, replicas + 1)
    ]
    return LaneCoverage(
        lane_id=lane_id,
        dispatched=len(runs),
        valid=sum(run.valid for run in runs),
        findings=findings,
        runs=runs,
    )


def complete_coverage() -> list[LaneCoverage]:
    return [
        lane_coverage("lane-a", findings=1),
        lane_coverage("lane-b", findings=1),
        lane_coverage("lane-c", findings=1),
    ]


def dispositions(merged: MergeResult) -> DispositionDocument:
    by_rule = {group.rule_id: group.key for group in merged.groups}
    return DispositionDocument(
        schema_version=1,
        dispositions=[
            DispositionRecord(
                finding_id=by_rule["rule/blocker"],
                decision=DispositionDecision.ACCEPTED,
                reason="owner accepts this release risk",
            ),
            DispositionRecord(
                finding_id=by_rule["rule/uncertain"],
                decision=DispositionDecision.ACCEPTED,
                reason="risk reviewed",
            ),
        ],
    )


def test_report_exposes_group_key_as_public_finding_id() -> None:
    merged, outcome = merged_outcome()
    report = render_report(
        target=target(),
        merged=merged,
        outcome=outcome,
        coverage=complete_coverage(),
        budget=None,
        synthesis=None,
    )

    for group in merged.groups:
        assert f"Finding ID: `{group.key}`" in report


@pytest.mark.parametrize(
    "coverage,match",
    [
        ([], "nonempty"),
        ([lane_coverage("lane-a", replicas=0)], "dispatched"),
        ([lane_coverage("lane-a", invalid={(1, 1)})], "invalid"),
        (
            [
                lane_coverage("lane-a"),
                lane_coverage("lane-a"),
            ],
            "duplicate",
        ),
    ],
)
def test_coverage_rejects_vacuous_invalid_and_duplicate_rows(
    coverage: list[LaneCoverage], match: str
) -> None:
    with pytest.raises(GateInvariantError, match=match):
        validate_coverage(["lane-a"], coverage, replicas=3, chunk_count=1)


def test_coverage_requires_exact_planned_lane_set() -> None:
    coverage = [lane_coverage("lane-a")]

    with pytest.raises(GateInvariantError, match=r"missing.*lane-b"):
        validate_coverage(["lane-a", "lane-b"], coverage, replicas=3, chunk_count=1)

    with pytest.raises(GateInvariantError, match=r"unexpected.*lane-a"):
        validate_coverage([], coverage, replicas=3, chunk_count=1)


def test_coverage_fails_closed_when_one_chunk_is_invalid_or_missing() -> None:
    invalid = [lane_coverage("lane-a", replicas=2, chunks=2, invalid={(2, 2)})]
    with pytest.raises(GateInvariantError, match=r"lane-a.*replica 2.*chunk 2.*invalid"):
        validate_coverage(["lane-a"], invalid, replicas=2, chunk_count=2)

    complete = lane_coverage("lane-a", replicas=2, chunks=2)
    missing_runs = complete.runs[:-1]
    missing = [
        LaneCoverage(
            lane_id="lane-a",
            dispatched=len(missing_runs),
            valid=len(missing_runs),
            findings=0,
            runs=missing_runs,
        )
    ]
    with pytest.raises(GateInvariantError, match=r"missing.*replica 2.*chunk 2"):
        validate_coverage(["lane-a"], missing, replicas=2, chunk_count=2)


def test_coverage_models_reject_duplicate_runs_and_invalid_run_findings() -> None:
    run = RunCoverage(
        replica=1,
        chunk=1,
        valid=True,
        findings=0,
        invalid_reason=None,
    )
    with pytest.raises(ValidationError, match="unique"):
        LaneCoverage(
            lane_id="lane-a",
            dispatched=2,
            valid=2,
            findings=0,
            runs=[run, run],
        )
    with pytest.raises(ValidationError, match="cannot have findings"):
        RunCoverage(
            replica=1,
            chunk=1,
            valid=False,
            findings=1,
            invalid_reason="scripted_invalid",
        )


def test_dispositions_reject_duplicate_omitted_unknown_and_rejected_ids() -> None:
    merged, outcome = merged_outcome()
    by_rule = {group.rule_id: group.key for group in merged.groups}
    duplicate = DispositionDocument(
        schema_version=1,
        dispositions=[
            DispositionRecord(
                finding_id=by_rule["rule/blocker"],
                decision=DispositionDecision.MUST_FIX,
                reason="fix",
            ),
            DispositionRecord(
                finding_id=by_rule["rule/blocker"],
                decision=DispositionDecision.MUST_FIX,
                reason="duplicate",
            ),
        ],
    )

    with pytest.raises(GateInvariantError, match="duplicate"):
        build_gate_verdict(
            run_id="run-1",
            target=target(),
            coverage=complete_coverage(),
            merged=merged,
            outcome=outcome,
            dispositions=duplicate,
        )

    for bad_id, match in [
        ("f" * 40, "unknown"),
        (by_rule["rule/rejected"], "unknown"),
    ]:
        document = DispositionDocument(
            schema_version=1,
            dispositions=[
                *dispositions(merged).dispositions,
                DispositionRecord(
                    finding_id=bad_id,
                    decision=DispositionDecision.MUST_FIX,
                    reason="not actionable",
                ),
            ],
        )
        with pytest.raises(GateInvariantError, match=match):
            build_gate_verdict(
                run_id="run-1",
                target=target(),
                coverage=complete_coverage(),
                merged=merged,
                outcome=outcome,
                dispositions=document,
                actor="owner",
                actor_permission="admin",
            )


def test_dispositions_require_nonblank_reason_and_strict_shape(tmp_path: Path) -> None:
    path = tmp_path / "dispositions.yaml"
    path.write_text(
        "schema_version: 1\ndispositions:\n  - finding_id: abc\n    decision: accepted\n"
        "    reason: '   '\n    forged: true\n",
        encoding="utf-8",
    )

    with pytest.raises((ValidationError, ValueError)):
        load_dispositions(path)


def test_disposition_inherited_from_is_optional_strict_and_round_trips(
    tmp_path: Path,
) -> None:
    absent = DispositionRecord(
        finding_id="finding-1",
        decision=DispositionDecision.ACCEPTED,
        reason="fresh judgment",
    )
    assert absent.inherited_from is None

    path = tmp_path / "dispositions.yaml"
    path.write_text(
        "schema_version: 1\ndispositions:\n"
        "  - finding_id: finding-1\n"
        "    decision: accepted\n"
        "    reason: prior owner judgment\n"
        "    inherited_from: run-prior\n",
        encoding="utf-8",
    )
    loaded = load_dispositions(path)
    assert loaded.dispositions[0].inherited_from == "run-prior"
    assert loaded.model_dump(mode="json")["dispositions"][0]["inherited_from"] == "run-prior"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DispositionRecord.model_validate(
            {
                "finding_id": "finding-1",
                "decision": "accepted",
                "reason": "owner judgment",
                "inherited_from": "run-prior",
                "forged": True,
            }
        )


def _inherited_finding(
    *,
    finding_id: str,
    rule_id: str,
    file: str,
    decision: DispositionDecision = DispositionDecision.ACCEPTED,
    reason: str = "prior owner judgment",
    hunk_sha256: str | None = None,
    body_sha256: str | None = None,
    severity: Severity = Severity.WARNING,
) -> GateFinding:
    return GateFinding(
        finding_id=finding_id,
        rule_id=rule_id,
        file=file,
        line=1,
        severity=severity,
        verdict=Verdict.CONFIRMED,
        disposition=decision,
        reason=reason,
        hunk_sha256=hunk_sha256,
        body_sha256=body_sha256,
    )


def _one_finding_merge(
    *, hunk_id: str = "src/a.py@@-1+1@@", verdict: Verdict = Verdict.CONFIRMED
) -> tuple[MergeResult, AdjudicationOutcome]:
    finding = EnrichedFinding(
        rule_id="rule/actionable",
        file="src/a.py",
        hunk_id=hunk_id,
        line=1,
        severity=Severity.WARNING,
        body="actionable",
        anchorable=True,
        lane_id="lane-a",
        replica=1,
    )
    merged = merge([finding], lane_tiers={"lane-a": Tier.BASE})
    key = merged.groups[0].key
    outcome = AdjudicationOutcome(
        verdicts={key: verdict},
        reasons={key: verdict.value.lower()},
        evidence={key: "evidence"},
        replica_votes={key: [verdict] * 3},
        unresolved=[],
        coerced_rejections=0,
    )
    return merged, outcome


def _multi_body_merge(bodies: list[str]) -> tuple[MergeResult, AdjudicationOutcome]:
    findings = [
        EnrichedFinding(
            rule_id="rule/actionable",
            file="src/a.py",
            hunk_id="src/a.py@@-1+1@@",
            line=1,
            severity=Severity.WARNING,
            body=body,
            anchorable=True,
            lane_id="lane-a",
            replica=index,
        )
        for index, body in enumerate(bodies, start=1)
    ]
    merged = merge(findings, lane_tiers={"lane-a": Tier.BASE})
    key = merged.groups[0].key
    outcome = AdjudicationOutcome(
        verdicts={key: Verdict.CONFIRMED},
        reasons={key: "confirmed"},
        evidence={key: "evidence"},
        replica_votes={key: [Verdict.CONFIRMED] * 3},
        unresolved=[],
        coerced_rejections=0,
    )
    return merged, outcome


def test_inheritance_matcher_exact_id_carries_and_unique_pair_prefills() -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]

    exact = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                hunk_sha256="1" * 64,
                body_sha256=BODY_SHA256,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64},
    )[group.key]
    assert exact.tier is InheritanceTier.EXACT_ID
    assert exact.decision is DispositionDecision.ACCEPTED
    assert exact.reason == "prior owner judgment"
    assert exact.inherited_from == "run-prior"

    moved = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id="different-id",
                rule_id=group.rule_id,
                file=group.file,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
    )[group.key]
    assert moved.tier is InheritanceTier.UNIQUE_PAIR
    assert moved.decision is DispositionDecision.MUST_FIX
    assert moved.reason == "prior owner judgment"
    assert moved.inherited_from == "run-prior"
    assert moved.blank_reason == "finding_id_changed"


def test_inheritance_matcher_rejects_exact_id_with_different_identity_pair() -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]

    matched = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id="rule/forged",
                file=group.file,
                hunk_sha256="1" * 64,
                body_sha256=BODY_SHA256,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64},
    )[group.key]

    assert matched.tier is None
    assert matched.decision is DispositionDecision.MUST_FIX
    assert matched.reason == ""
    assert matched.inherited_from is None
    assert matched.blank_reason is InheritanceBlankReason.IDENTITY_MISMATCH


def test_inheritance_matcher_demotes_exact_id_when_severity_changes() -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]
    merged.groups[0] = group.model_copy(update={"severity": Severity.BLOCKER})

    matched = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                hunk_sha256="1" * 64,
                body_sha256=BODY_SHA256,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64},
    )[group.key]

    assert matched.tier is InheritanceTier.UNIQUE_PAIR
    assert matched.decision is DispositionDecision.MUST_FIX
    assert matched.reason == "prior owner judgment"
    assert matched.blank_reason is InheritanceBlankReason.SEVERITY_CHANGED


def test_inheritance_matcher_rejects_orphan_outcome_keys() -> None:
    merged, outcome = _one_finding_merge()
    outcome.verdicts["orphan-finding"] = Verdict.CONFIRMED

    with pytest.raises(GateInvariantError, match="orphan-finding"):
        match_inherited_dispositions(
            [],
            merged,
            outcome,
            inherited_run_id="run-prior",
        )


@pytest.mark.parametrize(
    ("source_digest", "current_digest", "blank_reason"),
    [
        ("2" * 64, "1" * 64, "content_changed"),
        (None, "1" * 64, "source_digest_missing"),
        ("1" * 64, None, "current_digest_missing"),
    ],
)
def test_inheritance_matcher_demotes_exact_id_without_equal_known_hunk_digest(
    source_digest: str | None,
    current_digest: str | None,
    blank_reason: str,
) -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]

    result = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                hunk_sha256=source_digest,
                body_sha256=BODY_SHA256,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: current_digest},
    )[group.key]

    assert result.tier is InheritanceTier.UNIQUE_PAIR
    assert result.decision is DispositionDecision.MUST_FIX
    assert result.reason == "prior owner judgment"
    assert result.inherited_from == "run-prior"
    assert result.blank_reason == blank_reason


@pytest.mark.parametrize(
    ("source_digest", "blank_reason"),
    [
        ("2" * 64, "diagnosis_changed"),
        (None, "source_digest_missing"),
    ],
)
def test_inheritance_matcher_requires_equal_known_body_digest_for_exact_carry(
    source_digest: str | None,
    blank_reason: str,
) -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]

    result = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                hunk_sha256="1" * 64,
                body_sha256=source_digest,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64},
    )[group.key]

    assert result.tier is InheritanceTier.UNIQUE_PAIR
    assert result.decision is DispositionDecision.MUST_FIX
    assert result.blank_reason == blank_reason


def test_inheritance_body_digest_binds_all_bodies_and_is_order_insensitive() -> None:
    source_bodies = ["diagnosis A", "diagnosis B"]
    source_digest = body_set_sha256(*source_bodies)
    changed, changed_outcome = _multi_body_merge(["diagnosis A", "diagnosis C"])
    reordered, reordered_outcome = _multi_body_merge(list(reversed(source_bodies)))
    source = _inherited_finding(
        finding_id=changed.groups[0].key,
        rule_id=changed.groups[0].rule_id,
        file=changed.groups[0].file,
        hunk_sha256="1" * 64,
        body_sha256=source_digest,
    )

    changed_match = match_inherited_dispositions(
        [source],
        changed,
        changed_outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={changed.groups[0].key: "1" * 64},
    )[changed.groups[0].key]
    reordered_match = match_inherited_dispositions(
        [source],
        reordered,
        reordered_outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={reordered.groups[0].key: "1" * 64},
    )[reordered.groups[0].key]

    assert changed_match.tier is InheritanceTier.UNIQUE_PAIR
    assert changed_match.blank_reason is InheritanceBlankReason.DIAGNOSIS_CHANGED
    assert reordered_match.tier is InheritanceTier.EXACT_ID
    assert reordered_match.decision is DispositionDecision.ACCEPTED


def test_inheritance_body_digest_has_unambiguous_body_boundaries() -> None:
    separated, _ = _multi_body_merge(["a", "b"])
    injected, _ = _multi_body_merge(["a\n\0\nb"])

    assert _body_sha256(separated.groups[0]) != _body_sha256(injected.groups[0])


def test_legacy_delimited_body_digest_demotes_after_digest_migration() -> None:
    bodies = ["diagnosis A", "diagnosis B"]
    merged, outcome = _multi_body_merge(bodies)
    group = merged.groups[0]
    legacy_digest = hashlib.sha256("\n\0\n".join(sorted(bodies)).encode()).hexdigest()

    matched = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                hunk_sha256="1" * 64,
                body_sha256=legacy_digest,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64},
    )[group.key]

    assert matched.tier is InheritanceTier.UNIQUE_PAIR
    assert matched.blank_reason == "diagnosis_changed"


def test_empty_collapse_group_bodies_raise_gate_invariant() -> None:
    merged, outcome = _one_finding_merge()
    merged.groups[0] = merged.groups[0].model_copy(update={"bodies": []})

    with pytest.raises(GateInvariantError, match="body"):
        match_inherited_dispositions(
            [],
            merged,
            outcome,
            inherited_run_id="run-prior",
        )


def test_inheritance_matcher_ignores_must_fix_and_rejected_groups() -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]
    result = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id=group.key,
                rule_id=group.rule_id,
                file=group.file,
                decision=DispositionDecision.MUST_FIX,
                reason="still must fix",
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
    )[group.key]
    assert result.tier is None
    assert result.decision is DispositionDecision.MUST_FIX
    assert result.reason == ""
    assert result.inherited_from is None
    assert result.blank_reason == "prior_must_fix"

    rejected_merged, rejected_outcome = _one_finding_merge(verdict=Verdict.REJECTED)
    assert (
        match_inherited_dispositions(
            [
                _inherited_finding(
                    finding_id=rejected_merged.groups[0].key,
                    rule_id="rule/actionable",
                    file="src/a.py",
                )
            ],
            rejected_merged,
            rejected_outcome,
            inherited_run_id="run-prior",
        )
        == {}
    )


@pytest.mark.parametrize("duplicate_side", ["inherited", "current"])
def test_inheritance_matcher_leaves_ambiguous_pairs_blank(duplicate_side: str) -> None:
    findings = [
        EnrichedFinding(
            rule_id="rule/actionable",
            file="src/a.py",
            hunk_id="src/a.py@@-1+1@@",
            line=1,
            severity=Severity.WARNING,
            body="first",
            anchorable=True,
            lane_id="lane-a",
            replica=1,
        )
    ]
    if duplicate_side == "current":
        findings.append(
            findings[0].model_copy(
                update={"hunk_id": "src/a.py@@-10+10@@", "line": 10, "body": "second"}
            )
        )
    merged = merge(findings, lane_tiers={"lane-a": Tier.BASE})
    outcome = AdjudicationOutcome(
        verdicts={group.key: Verdict.CONFIRMED for group in merged.groups},
        reasons={group.key: "confirmed" for group in merged.groups},
        evidence={group.key: "evidence" for group in merged.groups},
        replica_votes={group.key: [Verdict.CONFIRMED] * 3 for group in merged.groups},
        unresolved=[],
        coerced_rejections=0,
    )
    exact_group = merged.groups[0]
    inherited = [
        _inherited_finding(
            finding_id=exact_group.key,
            rule_id="rule/actionable",
            file="src/a.py",
            hunk_sha256="1" * 64,
            body_sha256=body_set_sha256(*exact_group.bodies),
        )
    ]
    if duplicate_side == "inherited":
        inherited.append(
            _inherited_finding(
                finding_id="prior-2",
                rule_id="rule/actionable",
                file="src/a.py",
                decision=DispositionDecision.MUST_FIX,
                reason="still must fix",
            )
        )

    results = match_inherited_dispositions(
        inherited,
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={group.key: "1" * 64 for group in merged.groups},
    )

    assert results
    assert all(result.tier is None for result in results.values())
    assert all(result.reason == "" for result in results.values())
    expected_reason = (
        "source_pair_ambiguous" if duplicate_side == "inherited" else "current_pair_ambiguous"
    )
    assert all(result.blank_reason == expected_reason for result in results.values())


def test_owner_only_blocker_acceptance_and_must_fix_verdict() -> None:
    merged, outcome = merged_outcome()
    document = dispositions(merged)

    with pytest.raises(GateInvariantError, match="admin"):
        build_gate_verdict(
            run_id="run-1",
            target=target(),
            coverage=complete_coverage(),
            merged=merged,
            outcome=outcome,
            dispositions=document,
            actor="contributor",
            actor_permission="write",
        )

    accepted = build_gate_verdict(
        run_id="run-1",
        target=target(),
        coverage=complete_coverage(),
        merged=merged,
        outcome=outcome,
        dispositions=document,
        actor="repo-owner",
        actor_permission="admin",
    )
    assert accepted.verdict == "PASS"
    assert accepted.actor == "repo-owner"

    document.dispositions[0].decision = DispositionDecision.MUST_FIX
    blocked = build_gate_verdict(
        run_id="run-1",
        target=target(),
        coverage=complete_coverage(),
        merged=merged,
        outcome=outcome,
        dispositions=document,
    )
    assert blocked.verdict == "BLOCK"
    assert blocked.actor is None


def test_gate_artifacts_are_reconstructable_and_template_uses_public_ids(
    tmp_path: Path,
) -> None:
    merged, outcome = merged_outcome()
    document = dispositions(merged)
    verdict = build_gate_verdict(
        run_id="run-1",
        target=target(),
        coverage=complete_coverage(),
        merged=merged,
        outcome=outcome,
        dispositions=document,
        actor="repo-owner",
        actor_permission="admin",
    )

    markdown = render_gate_verdict(verdict)
    json_path, md_path = save_gate_verdict(tmp_path, verdict)
    template_path = write_disposition_template(tmp_path, merged, outcome)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["anchor"] == {"base_sha": "a" * 40, "head_sha": "b" * 40}
    assert payload["counts"] == {"CONFIRMED": 1, "REJECTED": 1, "UNCERTAIN": 1}
    assert len(payload["coverage"]) == 3
    assert {item["finding_id"] for item in payload["findings"]} == {
        record.finding_id for record in document.dispositions
    }
    assert "| Finding ID | Severity | Verdict | Disposition | Inherited from | Reason |" in markdown
    assert md_path.read_text(encoding="utf-8") == markdown
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    assert {item["finding_id"] for item in template["dispositions"]} == {
        record.finding_id for record in document.dispositions
    }
    assert {item["reason"] for item in template["dispositions"]} == {""}
    with pytest.raises(ValidationError, match="nonblank"):
        load_dispositions(template_path)


def test_gate_verdict_persists_hunk_content_digest_without_changing_finding_id() -> None:
    merged, outcome = _one_finding_merge(hunk_id="src/a.py@@-1,1+1,1@@")
    group = merged.groups[0]
    document = DispositionDocument(
        schema_version=1,
        dispositions=[
            DispositionRecord(
                finding_id=group.key,
                decision=DispositionDecision.ACCEPTED,
                reason="reviewed",
            )
        ],
    )

    verdict = build_gate_verdict(
        run_id="run-1",
        target=target().model_copy(update={"diff": HUNK_DIFF}),
        coverage=complete_coverage(),
        merged=merged,
        outcome=outcome,
        dispositions=document,
    )

    assert verdict.findings[0].finding_id == group.key
    assert verdict.findings[0].hunk_sha256 == HUNK_SHA256
    assert verdict.findings[0].body_sha256 == BODY_SHA256


def test_gate_verdict_persists_per_finding_inheritance_outcome() -> None:
    merged, outcome = _one_finding_merge()
    group = merged.groups[0]
    matches = match_inherited_dispositions(
        [
            _inherited_finding(
                finding_id="moved-id",
                rule_id=group.rule_id,
                file=group.file,
            )
        ],
        merged,
        outcome,
        inherited_run_id="run-prior",
    )
    document = DispositionDocument(
        schema_version=1,
        dispositions=[
            DispositionRecord(
                finding_id=group.key,
                decision=DispositionDecision.ACCEPTED,
                reason="consciously re-accepted",
                inherited_from="run-prior",
            )
        ],
    )

    verdict = build_gate_verdict(
        run_id="run-1",
        target=target(),
        coverage=complete_coverage(),
        merged=merged,
        outcome=outcome,
        dispositions=document,
        inherited_run_id="run-prior",
        inheritance=matches,
    )

    assert verdict.findings[0].inheritance_tier is InheritanceTier.UNIQUE_PAIR
    assert verdict.findings[0].inheritance_blank_reason == "finding_id_changed"


def test_inheritance_summary_reason_keys_use_closed_vocabulary() -> None:
    summary = InheritanceSummary(
        source_run_id="run-prior",
        carried=0,
        prefilled=0,
        blank=1,
        reasons={InheritanceBlankReason.UNMATCHED: 1},
    )

    assert summary.model_dump(mode="json")["reasons"] == {"unmatched": 1}
    with pytest.raises(ValidationError, match="Input should be"):
        InheritanceSummary.model_validate(
            {
                "source_run_id": "run-prior",
                "carried": 0,
                "prefilled": 0,
                "blank": 1,
                "reasons": {"invented_reason": 1},
            }
        )


def test_disposition_template_does_not_include_rejected_findings(tmp_path: Path) -> None:
    merged, outcome = merged_outcome()
    template_path = write_disposition_template(tmp_path, merged, outcome)
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    by_rule = {group.rule_id: group.key for group in merged.groups}

    assert by_rule["rule/rejected"] not in {item["finding_id"] for item in template["dispositions"]}


def test_disposition_template_renders_carried_prefilled_and_blank_entries(
    tmp_path: Path,
) -> None:
    merged, outcome = merged_outcome()
    by_rule = {group.rule_id: group for group in merged.groups}
    rejected = by_rule["rule/rejected"]
    outcome.verdicts[rejected.key] = Verdict.CONFIRMED
    inherited = [
        _inherited_finding(
            finding_id=by_rule["rule/blocker"].key,
            rule_id="rule/blocker",
            file="src/a.py",
            reason="exact acceptance",
            hunk_sha256="1" * 64,
            body_sha256=body_set_sha256("blocker"),
            severity=Severity.BLOCKER,
        ),
        _inherited_finding(
            finding_id="moved-finding-id",
            rule_id="rule/uncertain",
            file="src/b.py",
            reason="moved acceptance",
        ),
    ]
    matches = match_inherited_dispositions(
        inherited,
        merged,
        outcome,
        inherited_run_id="run-prior",
        current_hunk_sha256={by_rule["rule/blocker"].key: "1" * 64},
    )

    template_path = write_disposition_template(
        tmp_path,
        merged,
        outcome,
        inheritance=matches,
    )

    records = {
        item["finding_id"]: item
        for item in yaml.safe_load(template_path.read_text(encoding="utf-8"))["dispositions"]
    }
    assert records[by_rule["rule/blocker"].key] == {
        "finding_id": by_rule["rule/blocker"].key,
        "decision": "accepted",
        "reason": "exact acceptance",
        "inherited_from": "run-prior",
    }
    assert records[by_rule["rule/uncertain"].key] == {
        "finding_id": by_rule["rule/uncertain"].key,
        "decision": "must_fix",
        "reason": "moved acceptance",
        "inherited_from": "run-prior",
    }
    assert records[rejected.key] == {
        "finding_id": rejected.key,
        "decision": "must_fix",
        "reason": "",
    }
    assert "# blank_reason: unmatched" in template_path.read_text(encoding="utf-8")


def test_provision_checkout_clones_detaches_and_verifies_head_and_clean(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        commands.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return f"{'b' * 40}\n"
        return ""

    checkout = provision_checkout(
        repo="owner/repo",
        pr_number=42,
        head_sha="b" * 40,
        destination=tmp_path / "checkout",
        run=fake_run,
    )

    assert checkout == tmp_path / "checkout"
    assert commands == [
        ["gh", "repo", "clone", "owner/repo", str(checkout), "--", "--no-checkout"],
        [
            "git",
            "-C",
            str(checkout),
            "fetch",
            "--no-tags",
            "origin",
            "refs/pull/42/head",
        ],
        ["git", "-C", str(checkout), "checkout", "--detach", "b" * 40],
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        ["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=all"],
    ]


@pytest.mark.parametrize(
    ("head", "status", "match"), [("c" * 40, "", "HEAD"), ("b" * 40, "?? x", "clean")]
)
def test_provision_checkout_fails_on_wrong_head_or_dirty_tree(
    tmp_path: Path, head: str, status: str, match: str
) -> None:
    def fake_run(command: list[str]) -> str:
        if command[-2:] == ["rev-parse", "HEAD"]:
            return head
        if "status" in command:
            return status
        return ""

    with pytest.raises(GateInvariantError, match=match):
        provision_checkout(
            repo="owner/repo",
            pr_number=42,
            head_sha="b" * 40,
            destination=tmp_path / "checkout",
            run=fake_run,
        )


def test_gate_anchor_is_strict() -> None:
    anchor = GateAnchor(base_sha="a" * 40, head_sha="b" * 40)
    assert anchor.model_dump() == {"base_sha": "a" * 40, "head_sha": "b" * 40}
    with pytest.raises(ValidationError):
        GateAnchor(base_sha="short", head_sha="b" * 40)


def test_gate_plan_round_trip_is_strict(tmp_path: Path) -> None:
    plan = GatePlan(
        schema_version=1,
        lane_ids=["lane-a", "lane-b"],
        replicas=3,
        adjudicate_replicas=1,
        chunk_count=2,
    )
    path = save_gate_plan(tmp_path, plan)

    assert load_gate_plan(tmp_path) == plan
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["replicas"] == 3
    assert raw["adjudicate_replicas"] == 1
    raw["extra"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_gate_plan(tmp_path)


def test_legacy_gate_plan_derives_adjudicate_replicas_from_replicas(tmp_path: Path) -> None:
    """Pre-split plans ran one combined count: their historical adjudication
    count IS the stored replicas value, never the new default of 3."""

    legacy = {
        "schema_version": 1,
        "lane_ids": ["lane-a"],
        "replicas": 1,
        "chunk_count": 1,
    }
    (tmp_path / "gate-plan.json").write_text(json.dumps(legacy), encoding="utf-8")

    plan = load_gate_plan(tmp_path)
    assert plan.replicas == 1
    assert plan.adjudicate_replicas == 1

    legacy["replicas"] = 3
    (tmp_path / "gate-plan.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert load_gate_plan(tmp_path).adjudicate_replicas == 3


def test_pull_request_requery_and_actor_permission_commands() -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        commands.append(command)
        if command[:3] == ["gh", "api", "user"]:
            return "repo-owner\n"
        if "collaborators" in command[2]:
            return "admin\n"
        return json.dumps(
            {
                "base": {"sha": "a" * 40},
                "head": {"sha": "b" * 40},
                "state": "open",
                "merged": False,
            }
        )

    state = query_pull_request("owner/repo", 42, run=fake_run)
    actor, permission = github_actor_permission("owner/repo", run=fake_run)

    assert state == PullRequestState(
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="open",
        merged=False,
    )
    assert (actor, permission) == ("repo-owner", "admin")
    assert commands == [
        ["gh", "api", "repos/owner/repo/pulls/42"],
        ["gh", "api", "user", "--jq", ".login"],
        [
            "gh",
            "api",
            "repos/owner/repo/collaborators/repo-owner/permission",
            "--jq",
            ".permission",
        ],
    ]


def test_authorization_diagnostic_redacts_token_families_and_controls() -> None:
    secrets = [
        "ghp_" + "A" * 36,
        "gho_" + "B" * 36,
        "ghu_" + "C" * 36,
        "ghs_" + "D" * 36,
        "ghr_" + "E" * 36,
        "github_pat_" + "11AA22BB33CC44DD55EE66FF",
        "f" * 80,
        "QWxhZGRpbjpvcGVuIHNlc2FtZQ" * 4,
    ]

    def failed_run(command: list[str]) -> str:
        raise subprocess.CalledProcessError(
            returncode=19,
            cmd=command,
            stderr=(
                "\x00".join(secrets)
                + "\nAuthorization: Basic private-value\n"
                + "Bearer another-private-value\n"
            ),
        )

    with pytest.raises(GitHubAuthorizationError) as caught:
        github_actor_permission("owner/repo", run=failed_run)

    detail = caught.value.detail
    assert caught.value.step == "actor_lookup"
    assert "exit status 19" in detail
    assert "Authorization: [REDACTED]" in detail
    assert "Bearer [REDACTED]" in detail
    assert "\x00" not in detail
    assert all(secret not in detail for secret in secrets)
    assert len(detail) <= 500


def test_authorization_diagnostic_redacts_base64url_credentials() -> None:
    credential = "Ab1_-" * 12

    redacted = _redact_subprocess_diagnostic(f"credential={credential}")

    assert credential not in redacted
    assert redacted == "credential=[REDACTED]"


@pytest.mark.parametrize(
    ("diagnostic", "credential"),
    [
        ("Authori\x00zation: Basic secret", "Basic secret"),
        ("gh\x01p_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "ghp_AAAAAAAAAA"),
    ],
)
def test_authorization_diagnostic_deletes_controls_before_redacting_credentials(
    diagnostic: str,
    credential: str,
) -> None:
    redacted = _redact_subprocess_diagnostic(diagnostic)

    assert credential not in redacted
    assert "[REDACTED]" in redacted
    assert all(ord(character) >= 32 for character in redacted)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "rvw-20260731-030510-pr-8",
        "ordinary-hyphenated-words-remain-readable-across-long-diagnostics",
    ],
)
def test_authorization_diagnostic_preserves_non_credentials(diagnostic: str) -> None:
    assert _redact_subprocess_diagnostic(diagnostic) == diagnostic


@pytest.mark.parametrize(
    ("diagnostic", "credential"),
    [
        ("ghp_\u202eSECRET123", "ghp_SECRET123"),
        ("Authori\u200bzation: Basic private-value", "Basic private-value"),
        ("Bearer\u200e private-value", "private-value"),
    ],
)
def test_authorization_diagnostic_normalizes_before_redacting(
    diagnostic: str,
    credential: str,
) -> None:
    def failed_run(command: list[str]) -> str:
        raise subprocess.CalledProcessError(
            returncode=19,
            cmd=command,
            stderr=diagnostic,
        )

    with pytest.raises(GitHubAuthorizationError) as caught:
        github_actor_permission("owner/repo", run=failed_run)

    assert credential not in caught.value.detail
    assert "[REDACTED]" in caught.value.detail


@pytest.mark.parametrize(
    ("actor_output", "permission_output", "step", "actor"),
    [
        ("   \n", "admin\n", "actor_lookup", None),
        ("repo-owner\n", " \t\n", "permission_lookup", "repo-owner"),
    ],
)
def test_authorization_lookup_rejects_empty_success_output(
    actor_output: str,
    permission_output: str,
    step: str,
    actor: str | None,
) -> None:
    def fake_run(command: list[str]) -> str:
        if command[:3] == ["gh", "api", "user"]:
            return actor_output
        return permission_output

    with pytest.raises(GitHubAuthorizationError) as caught:
        github_actor_permission("owner/repo", run=fake_run)

    assert caught.value.step == step
    assert caught.value.actor == actor
    assert "empty" in caught.value.detail


def test_gate_verdict_legacy_kind_inference_and_closed_blank_reasons() -> None:
    base = GateVerdict(
        run_id="run-1",
        repo="owner/repo",
        pr_number=42,
        anchor=GateAnchor(base_sha="a" * 40, head_sha="b" * 40),
        counts={"CONFIRMED": 0, "REJECTED": 0, "UNCERTAIN": 0},
        coverage=[],
        findings=[],
        verdict="BLOCK",
        failures=[ACTIONABLE_DISPOSITIONS_PAUSE],
    )
    raw = base.model_dump(mode="json", exclude={"kind"})
    assert GateVerdict.model_validate(raw).kind == "pause"
    raw["failures"] = ["operational failure"]
    assert GateVerdict.model_validate(raw).kind == "failure"
    raw["findings"] = [
        GateFinding(
            finding_id="finding-1",
            rule_id="rule/actionable",
            file="src/a.py",
            line=1,
            severity=Severity.WARNING,
            verdict=Verdict.CONFIRMED,
            disposition=DispositionDecision.ACCEPTED,
            reason="reviewed",
        ).model_dump(mode="json")
    ]
    assert GateVerdict.model_validate(raw).kind == "completed"

    raw["findings"][0]["inheritance_blank_reason"] = "content_digest_unknown"
    with pytest.raises(ValidationError):
        GateVerdict.model_validate(raw)


def test_actionable_dispositions_pause_sentinel_has_one_source_definition() -> None:
    source_root = Path(__file__).parents[1] / "src"
    sentinel = ACTIONABLE_DISPOSITIONS_PAUSE

    occurrences = sum(
        path.read_text(encoding="utf-8").count(sentinel) for path in source_root.rglob("*.py")
    )

    assert occurrences == 1


def test_pull_request_requery_rejects_malformed_api_data() -> None:
    with pytest.raises(ValueError, match="invalid pull-request state"):
        query_pull_request("owner/repo", 42, run=lambda command: "{}")


@pytest.mark.parametrize(
    "state,match",
    [
        (
            PullRequestState(base_sha="a" * 40, head_sha="c" * 40, state="open", merged=False),
            "stale",
        ),
        (
            PullRequestState(base_sha="c" * 40, head_sha="b" * 40, state="open", merged=False),
            "stale",
        ),
        (
            PullRequestState(base_sha="a" * 40, head_sha="b" * 40, state="closed", merged=True),
            "open and unmerged",
        ),
    ],
)
def test_pull_request_verification_fails_closed(state: PullRequestState, match: str) -> None:
    with pytest.raises(GateInvariantError, match=match):
        verify_pull_request(GateAnchor(base_sha="a" * 40, head_sha="b" * 40), state)
