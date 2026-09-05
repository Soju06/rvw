from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rvw.lane_lint as lane_lint_module
from rvw.cli import app
from rvw.lane import load_new_lane
from rvw.registry import Registry, _glob_match

runner = CliRunner()


def _write_lane(
    path: Path,
    *,
    lane: str,
    tier: str,
    body: str,
    metadata: str = "",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nlane: {lane}\ntier: {tier}\n{metadata}---\n# {lane}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_leading_double_star_matches_root_and_nested_paths_case_sensitively() -> None:
    assert _glob_match("main.py", "**/*.py")
    assert _glob_match("src/main.py", "**/*.py")
    assert _glob_match(r"src\main.py", r"**\*.py")
    assert not _glob_match("MAIN.PY", "**/*.py")


def test_lane_loader_rejects_brace_globs_with_stable_reason(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "brace.md",
        lane="scope/brace",
        tier="scope",
        metadata='when:\n  paths: ["**/*.{ts,py}"]\n',
        body="## rule: brace/rule\nAn observable defect.",
    )

    with pytest.raises(ValueError, match=r"unsupported-glob-braces.*separate patterns"):
        load_new_lane(path)


def test_legacy_registry_rejects_brace_globs_with_stable_reason() -> None:
    with pytest.raises(ValueError, match=r"unsupported-glob-braces.*separate patterns"):
        Registry.model_validate(
            {
                "layers": [
                    {
                        "id": "scope/brace",
                        "tier": "scope",
                        "lanes": ["brace"],
                        "when": {"paths": ["**/*.{ts,py}"]},
                    }
                ]
            }
        )


def test_schedule_hint_and_legacy_cost_have_the_same_runtime_value(tmp_path: Path) -> None:
    modern_path = _write_lane(
        tmp_path / "modern.md",
        lane="modern",
        tier="base",
        metadata="schedule_hint: heavy\n",
        body="## rule: modern/rule\nAn observable defect.",
    )
    legacy_path = _write_lane(
        tmp_path / "legacy.md",
        lane="legacy",
        tier="base",
        metadata="cost: heavy\n",
        body="## rule: legacy/rule\nAn observable defect.",
    )

    modern = load_new_lane(modern_path)
    with pytest.warns(FutureWarning, match="cost.*deprecated.*schedule_hint"):
        legacy = load_new_lane(legacy_path)

    assert modern.schedule_hint == legacy.schedule_hint == "heavy"
    assert modern.cost == legacy.cost == "heavy"


def test_lane_rejects_cost_and_schedule_hint_together(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "conflict.md",
        lane="conflict",
        tier="base",
        metadata="schedule_hint: heavy\ncost: light\n",
        body="## rule: conflict/rule\nAn observable defect.",
    )

    with pytest.raises(ValueError, match=r"cost.*schedule_hint.*cannot.*together"):
        load_new_lane(path)


def test_scope_lint_reports_whole_prompt_term_with_original_line_and_rule(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "base.md",
        lane="bad-base",
        tier="base",
        body=(
            "- `bad/component` — Require every component to render a spinner.\n\n"
            "## rule: bad/component\nThe rule is defined by lane guidance above."
        ),
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    diagnostic = next(error for error in payload["errors"] if error["evidence"] == "component")
    assert diagnostic == {
        "reason": "scope-domain-mismatch",
        "path": str(path),
        "line": 7,
        "rule_id": "bad/component",
        "domain": "frontend",
        "evidence": "component",
        "severity": "error",
        "message": "base lane uses frontend-specific term 'component'",
    }


@pytest.mark.parametrize(
    ("metadata", "body"),
    [
        (
            "lint:\n  allow-scope-terms: [component]\n",
            "## rule: generic/example\nA component is only an example.",
        ),
        (
            "",
            "<!-- lint-allow: component -->\n"
            "## rule: generic/example\nA component is only an example.",
        ),
    ],
)
def test_scope_lint_accepts_exact_frontmatter_and_inline_exceptions(
    tmp_path: Path, metadata: str, body: str
) -> None:
    path = _write_lane(
        tmp_path / "allowed.md",
        lane="allowed-base",
        tier="base",
        metadata=metadata,
        body=body,
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", "--path", str(path)])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["errors"] == []


def test_scope_lint_flags_isolated_project_rule_that_duplicates_packaged_base(
    tmp_path: Path,
) -> None:
    _write_lane(
        tmp_path / "project.md",
        lane="consumer/project",
        tier="project",
        body="## rule: bug/severe-defect\nA project restatement.",
    )

    result = runner.invoke(
        app,
        ["lanes", "lint", "--scope", "--json", "--path", str(tmp_path)],
    )

    assert result.exit_code == 1
    duplicate = next(
        error
        for error in json.loads(result.stdout)["errors"]
        if error["reason"] == "duplicate-rule-candidate"
    )
    assert duplicate["rule_id"] == "bug/severe-defect"
    assert duplicate["duplicate_of"] == "bug/severe-defect"
    assert duplicate["domain"] == "base-duplication"


def test_scope_lint_flags_project_rule_with_same_first_sentence_as_supplied_base(
    tmp_path: Path,
) -> None:
    sentence = "A changed result must preserve the caller-visible contract."
    _write_lane(
        tmp_path / "base.md",
        lane="unique-base",
        tier="base",
        body=f"## rule: unique/base-contract\n{sentence}\nMore base detail.",
    )
    _write_lane(
        tmp_path / "project.md",
        lane="consumer/project",
        tier="project",
        body=f"## rule: consumer/repeated-contract\n{sentence}\nProject detail.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(tmp_path)])

    assert result.exit_code == 1
    duplicate = next(
        error
        for error in json.loads(result.stdout)["errors"]
        if error["reason"] == "duplicate-rule-candidate"
    )
    assert duplicate["rule_id"] == "consumer/repeated-contract"
    assert duplicate["duplicate_of"] == "unique/base-contract"
    assert duplicate["evidence"] == "a changed result must preserve the caller visible contract"


def test_scope_lint_flags_backend_scope_with_language_wide_activation(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "backend.md",
        lane="backend-observability",
        tier="scope",
        metadata='when:\n  paths: ["**/*.py"]\n',
        body="## rule: backend/trace\nFailures must retain a correlation id.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    diagnostic = next(
        error
        for error in json.loads(result.stdout)["errors"]
        if error["reason"] == "scope-activation-too-broad"
    )
    assert diagnostic["domain"] == "backend"
    assert diagnostic["evidence"] == "**/*.py"


@pytest.mark.parametrize(
    ("lane", "paths", "body", "domain", "evidence"),
    [
        (
            "delivery-check",
            '["apps/web/**"]',
            "An HTTP handler must record the request.",
            "backend",
            "HTTP handler",
        ),
        (
            "delivery-check",
            '["server/**"]',
            "Every component must expose the state.",
            "frontend",
            "component",
        ),
    ],
)
def test_scope_lint_infers_opposing_domains_from_paths(
    tmp_path: Path,
    lane: str,
    paths: str,
    body: str,
    domain: str,
    evidence: str,
) -> None:
    path = _write_lane(
        tmp_path / f"{domain}.md",
        lane=lane,
        tier="scope",
        metadata=f"when:\n  paths: {paths}\n",
        body=f"## rule: check/{domain}\n{body}",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    errors = json.loads(result.stdout)["errors"]
    assert any(error["domain"] == domain and error["evidence"] == evidence for error in errors)


def test_scope_lint_exception_is_exact_and_does_not_hide_another_term(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "exact.md",
        lane="exact-base",
        tier="base",
        metadata="lint:\n  allow-scope-terms: [component]\n",
        body="## rule: exact/rule\nA component may render a value.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    evidence = {error["evidence"] for error in json.loads(result.stdout)["errors"]}
    assert "component" not in evidence
    assert "render" in evidence


def test_scope_lint_ignores_domain_terms_that_appear_only_in_rule_heading(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "heading.md",
        lane="generic-base",
        tier="base",
        body="## rule: frontend/component\nA result must preserve its declared shape.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 0, result.stdout


def test_lane_lint_frontmatter_is_strictly_typed(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "unknown.md",
        lane="unknown-lint-key",
        tier="base",
        metadata="lint:\n  allow-anything: true\n",
        body="## rule: generic/rule\nA result must preserve its declared shape.",
    )

    with pytest.raises(ValueError, match="allow-anything"):
        load_new_lane(path)


def test_scope_lint_reports_brace_glob_reason_through_cli(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "brace-cli.md",
        lane="scope/brace-cli",
        tier="scope",
        metadata='when:\n  paths: ["**/*.{ts,py}"]\n',
        body="## rule: brace/cli\nA result must preserve its declared shape.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    error = json.loads(result.stdout)["errors"][0]
    assert error["reason"] == "unsupported-glob-braces"
    assert "list separate patterns" in error["message"]


def test_inline_exception_applies_only_to_its_rule_section(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "local-exception.md",
        lane="local-exception",
        tier="base",
        body=(
            "<!-- lint-allow: component -->\n"
            "## rule: allowed/component-example\n"
            "A component is an example here.\n\n"
            "## rule: disallowed/component-mandate\n"
            "A component must render a spinner."
        ),
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    component_errors = [
        error for error in json.loads(result.stdout)["errors"] if error["evidence"] == "component"
    ]
    assert [error["rule_id"] for error in component_errors] == ["disallowed/component-mandate"]


def test_same_line_inline_exception_does_not_leak_to_next_rule(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "same-line-exception.md",
        lane="same-line-exception",
        tier="base",
        body=(
            "## rule: allowed/same-line\n"
            "A component is an example. <!-- lint-allow: component -->\n\n"
            "## rule: disallowed/next-rule\n"
            "A component must render a spinner."
        ),
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    component_errors = [
        error for error in json.loads(result.stdout)["errors"] if error["evidence"] == "component"
    ]
    assert [error["rule_id"] for error in component_errors] == ["disallowed/next-rule"]


def test_guidance_rule_id_tokens_do_not_trigger_scope_terms(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "guidance-token.md",
        lane="guidance-token",
        tier="base",
        body=(
            "- `frontend/component` — Preserve the declared value shape.\n\n"
            "## rule: frontend/component\n"
            "The rule is defined by the lane guidance above."
        ),
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 0, result.stdout


def test_scope_lint_preserves_non_rule_inline_code_examples(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "inline-example.md",
        lane="inline-example",
        tier="base",
        body=(
            "- `generic/example` — A `component` — followed by punctuation — is still an example.\n\n"
            "## rule: generic/example\n"
            "The rule is defined by the lane guidance above."
        ),
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 1
    errors = json.loads(result.stdout)["errors"]
    assert any(error["evidence"] == "component" for error in errors)


def test_scope_domain_tokens_require_path_boundaries(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "build.md",
        lane="build-suite",
        tier="scope",
        metadata='when:\n  paths: ["build/**"]\n',
        body="## rule: build/check\nAn HTTP handler is mentioned without a declared domain.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 0, result.stdout


def test_code_idiom_markers_are_case_sensitive(tmp_path: Path) -> None:
    path = _write_lane(
        tmp_path / "case.md",
        lane="case-sensitive-base",
        tier="base",
        body="## rule: generic/case\nThe phrase AS ANY is ordinary prose here.",
    )

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(path)])

    assert result.exit_code == 0, result.stdout


def test_duplicate_sentence_uses_multiline_guidance_for_placeholder_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "packaged"
    _write_lane(
        packaged / "base.md",
        lane="wrapped-base",
        tier="base",
        body=(
            "- `wrapped/contract` — A changed result must preserve the declared\n"
            "  caller-visible contract. Verification compares both shapes.\n\n"
            "## rule: wrapped/contract\n"
            "The rule is defined by lane guidance above."
        ),
    )
    project = _write_lane(
        tmp_path / "project.md",
        lane="consumer/wrapped",
        tier="project",
        body=(
            "## rule: consumer/contract\n"
            "A changed result must preserve the declared caller-visible contract."
        ),
    )
    monkeypatch.setattr(lane_lint_module, "_PACKAGED_BASE_ROOT", packaged)

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(project)])

    assert result.exit_code == 1
    duplicate = json.loads(result.stdout)["errors"][0]
    assert duplicate["reason"] == "duplicate-rule-candidate"
    assert duplicate["duplicate_of"] == "wrapped/contract"


def test_malformed_packaged_base_is_a_structured_scope_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / "invalid.md").write_text(
        "---\nlane: invalid\ntier: base\n# missing delimiter\n",
        encoding="utf-8",
    )
    project = _write_lane(
        tmp_path / "project.md",
        lane="consumer/project",
        tier="project",
        body="## rule: consumer/rule\nA project-specific property.",
    )
    monkeypatch.setattr(lane_lint_module, "_PACKAGED_BASE_ROOT", packaged)

    result = runner.invoke(app, ["lanes", "lint", "--scope", "--json", str(project)])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"][0]["reason"] == "malformed-frontmatter"
    assert payload["errors"][0]["path"] == str(packaged / "invalid.md")
