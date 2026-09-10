"""Repository publication controls preserve defaults and bound inline/thread writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_publish_policy import strict_policy
from test_publish_threads import (
    BOT,
    github_with,
    group_key,
    marker_body,
    node,
    prepared_run,
    threads_page,
)

import rvw.publish as publish_module
from rvw.policy import PublishPolicy, PublishPolicyInvalid
from rvw.publish import publish_review
from rvw.schema import Severity
from rvw.summary import ExecutionSummary
from rvw.synthesis import SynthesisDocument, SynthesisFinding


def test_publication_controls_default_and_legacy_channels() -> None:
    normal = strict_policy().publish
    assert normal.channels == ["checks", "review"]
    assert normal.checks.model_dump() == {"on_block": "failure", "on_pass": "success"}
    assert normal.inline.model_dump() == {"severity_at_least": "suggestion", "max_comments": None}
    assert strict_policy(publish_state="none").publish.channels == ["checks"]
    assert strict_policy(
        publish_state="none", publish={"channels": ["review"]}
    ).publish.channels == ["review"]


@pytest.mark.parametrize(
    "publish",
    [
        {"channels": []},
        {"channels": "checks"},
        {"channels": ["unknown"]},
        {"channels": [True]},
        {"checks": {"on_pass": "failure"}},
        {"checks": {"on_block": "success"}},
        {"checks": {"unknown": "neutral"}},
        {"checks": None},
        {"inline": {"severity_at_least": "critical"}},
        {"inline": {"max_comments": -1}},
        {"inline": {"max_comments": True}},
        {"inline": {"max_comments": "1"}},
        {"inline": {"max_comments": 1.5}},
        {"inline": {"unknown": 1}},
    ],
)
def test_invalid_publication_controls_fail_closed(publish: dict[str, object]) -> None:
    with pytest.raises(PublishPolicyInvalid):
        strict_policy(publish=publish)


def synthesized_run(tmp_path: Path):
    run, merged, outcome = prepared_run(tmp_path)
    merged.groups[0].severity = Severity.SUGGESTION
    merged.groups[1].severity = Severity.WARNING
    merged.groups[2].severity = Severity.BLOCKER
    run.save_merge(merged)
    synthesis = SynthesisDocument(
        overview="The change updates how requests are processed.",
        first_action="Correct the failing operation before merging the change.",
        findings=[
            SynthesisFinding(
                key=g.key,
                title="The operation can fail during request processing.",
                what="Full explanation remains available to the reader.",
                consequence="Requests can fail before their work is completed.",
                fix="Handle the failing operation before continuing request processing.",
            )
            for g in merged.groups
        ],
    )
    run.save_synthesis(synthesis)
    return run, merged, outcome


@pytest.mark.parametrize("floor,expected", [("suggestion", 3), ("warning", 2), ("blocker", 1)])
def test_inline_floor_keeps_body_only_findings_in_full(
    tmp_path: Path, floor: str, expected: int
) -> None:
    run, merged, outcome = synthesized_run(tmp_path)
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        publish_policy=PublishPolicy.model_validate({"inline": {"severity_at_least": floor}}),
    )
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert result.inline_count == expected
    assert payload["body"].count("Full explanation remains") == 3 - expected
    assert result.facts is not None
    assert result.facts.inline_policy.body_only_count == 3 - expected
    assert result.facts.inline_policy.severity_at_least == floor


@pytest.mark.parametrize("cap", [0, 1, 2])
def test_inline_cap_prefers_severity_with_stable_ties(tmp_path: Path, cap: int) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    merged.groups[0].severity = Severity.SUGGESTION
    policy = PublishPolicy.model_validate({"inline": {"max_comments": cap}})
    selected = []
    for groups in (merged.groups, list(reversed(merged.groups))):
        candidate_merge = merged.model_copy(update={"groups": groups})
        result = publish_review(
            run=run,
            repo="owner/repo",
            pr_number=42,
            report_md="",
            merged=candidate_merge,
            outcome=outcome,
            execute=False,
            publish_policy=policy,
        )
        payload = json.loads((run.dir / "publish-payload.json").read_text())
        selected.append([(c["path"], c["line"]) for c in payload.get("comments", [])])
        assert result.inline_count == cap
    assert selected[0] == selected[1]
    assert (merged.groups[0].file, merged.groups[0].line) not in selected[0]


def test_body_only_policy_leaves_existing_matching_thread_untouched(tmp_path: Path) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    key = group_key(merged, "r/same")
    next(group for group in merged.groups if group.key == key).severity = Severity.SUGGESTION
    github = github_with(
        [
            threads_page(
                [
                    node(
                        "body-only",
                        marker_body("r/same", "src/a.py", "evidence r/same"),
                        path="src/a.py",
                        line=10,
                        original_line=10,
                    ),
                ]
            )
        ]
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        plan_threads=True,
        identity=BOT,
        github=github,
        publish_policy=PublishPolicy.model_validate({"inline": {"severity_at_least": "warning"}}),
    )
    assert result.inline_count == 2
    assert result.facts is not None
    assert result.facts.reused_thread_ids == []
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert payload["plan"]["reuse"] == {}
    assert payload["plan"]["resolve"] == []
    assert payload["plan"]["supersede"] == []


def test_checks_only_never_calls_github_and_persists_policy_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    monkeypatch.setattr(publish_module, "_run", lambda *_: pytest.fail("review write"))
    github = github_with([])
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=True,
        plan_threads=True,
        identity=BOT,
        github=github,
        publish_policy=PublishPolicy.model_validate({"channels": ["checks"]}),
    )
    assert result.state == "skipped" and result.inline_count == 0
    assert github.calls == []
    summary = ExecutionSummary.model_validate_json((run.dir / "summary.json").read_text())
    assert summary.publish.channels == ["checks"]
    assert summary.publish.inline_policy.body_only_count == 3


def test_runtime_failure_retains_resolved_publication_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_cli_phase5 import fixture_artifacts, policy_file
    from typer.testing import CliRunner

    import rvw.cli as cli
    from rvw.presentation import PresentationConfig

    artifacts = fixture_artifacts(tmp_path, adjudicated=True)
    monkeypatch.setattr(cli, "_resolve_cli_target", lambda _: artifacts.target)
    monkeypatch.setattr(cli, "load_repo_presentation", lambda *_, **__: PresentationConfig())
    monkeypatch.setattr(cli, "provision_checkout", lambda **_: Path.cwd())

    async def fail(**kwargs: object):
        raise RuntimeError("fixture unavailable")

    monkeypatch.setattr(cli, "_execute_pipeline", fail)
    policy = policy_file(tmp_path, "none")
    policy.write_text(
        policy.read_text()
        + "publish:\n  inline:\n    severity_at_least: warning\n    max_comments: 1\n"
    )
    out = tmp_path / "failure"
    result = CliRunner().invoke(
        cli.app, ["run", "--target", "42", "--policy", str(policy), "--out", str(out), "--json"]
    )
    assert result.exit_code == 3
    summary = ExecutionSummary.model_validate_json((out / "summary.json").read_text())
    assert summary.publish.channels == ["checks"]
    assert summary.publish.inline_policy.severity_at_least == "warning"
    assert summary.publish.inline_policy.max_comments == 1


def test_zero_inline_cap_disables_living_thread_mutations(tmp_path: Path) -> None:
    run, merged, outcome = prepared_run(tmp_path, empty=True)
    github = github_with(
        [
            threads_page(
                [
                    node(
                        "old",
                        marker_body("r/old", "src/a.py", "gone()"),
                        path="src/a.py",
                        line=None,
                        original_line=3,
                        outdated=True,
                    ),
                ]
            )
        ]
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        plan_threads=True,
        identity=BOT,
        github=github,
        publish_policy=PublishPolicy.model_validate({"inline": {"max_comments": 0}}),
    )
    assert result.facts is not None
    assert result.facts.threads_skipped_reason == "disabled_by_policy"
    assert all(kind != "threads" for kind, _ in github.calls)


def test_body_only_finding_does_not_hide_inline_thread_with_same_rule_and_path(
    tmp_path: Path,
) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    body_only, inline = merged.groups[:2]
    body_only.rule_id = inline.rule_id = "r/shared"
    body_only.severity = Severity.SUGGESTION
    body_only.file = inline.file = "src/a.py"
    body_only.line, inline.line = 10, 20
    outcome.evidence[body_only.key] = "first evidence"
    outcome.evidence[inline.key] = "second evidence"
    github = github_with(
        [
            threads_page(
                [
                    node(
                        "body-only",
                        marker_body("r/shared", "src/a.py", "first evidence"),
                        path="src/a.py",
                        line=10,
                        original_line=10,
                    ),
                    node(
                        "inline",
                        marker_body("r/shared", "src/a.py", "second evidence"),
                        path="src/a.py",
                        line=20,
                        original_line=20,
                    ),
                ]
            )
        ]
    )
    result = publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        plan_threads=True,
        identity=BOT,
        github=github,
        publish_policy=PublishPolicy.model_validate({"inline": {"severity_at_least": "warning"}}),
    )
    assert result.facts is not None
    assert result.facts.reused_thread_ids == ["inline"]
    assert result.inline_count == 1
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert payload["plan"]["reuse"] == {inline.key: "inline"}
    assert payload["plan"]["resolve"] == []


@pytest.mark.parametrize(
    "section,field",
    [
        ("checks", "on_block"),
        ("checks", "on_pass"),
        ("inline", "severity_at_least"),
    ],
)
def test_null_is_not_an_omitted_publication_setting(section: str, field: str) -> None:
    with pytest.raises(PublishPolicyInvalid):
        strict_policy(publish={section: {field: None}})


def test_changed_body_only_evidence_does_not_resolve_the_previous_thread(tmp_path: Path) -> None:
    run, merged, outcome = prepared_run(tmp_path)
    current = next(g for g in merged.groups if g.rule_id == "r/same")
    current.severity = Severity.SUGGESTION
    github = github_with(
        [
            threads_page(
                [
                    node(
                        "old-body",
                        marker_body("r/same", "src/a.py", "previous evidence"),
                        path="src/a.py",
                        line=None,
                        original_line=3,
                        outdated=True,
                    ),
                ]
            )
        ]
    )
    publish_review(
        run=run,
        repo="owner/repo",
        pr_number=42,
        report_md="",
        merged=merged,
        outcome=outcome,
        execute=False,
        plan_threads=True,
        identity=BOT,
        github=github,
        publish_policy=PublishPolicy.model_validate({"inline": {"severity_at_least": "warning"}}),
    )
    payload = json.loads((run.dir / "publish-payload.json").read_text())
    assert payload["plan"]["resolve"] == []
    assert payload["plan"]["supersede"] == []
    assert payload["plan"]["reuse"] == {}


@pytest.mark.parametrize(
    "case",
    json.loads((Path(__file__).parent / "fixtures/publication_policy_contract.json").read_text()),
    ids=lambda case: case["name"],
)
def test_shared_publication_policy_contract(case: dict[str, object]) -> None:
    import yaml

    from rvw.policy import validate_policy

    raw = yaml.safe_load(str(case["yaml"]))
    if "expected_error" in case:
        with pytest.raises(PublishPolicyInvalid) as error:
            validate_policy(raw)
        assert error.value.reason == case["expected_error"]
    else:
        policy = validate_policy(raw).publish.model_dump()
        assert {key: policy[key] for key in ("channels", "checks", "inline")} == case["expected"]
