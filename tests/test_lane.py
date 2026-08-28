from pathlib import Path
from typing import cast

from rvw.lane import Lane, load_lane

FIXTURES = Path(__file__).parent / "fixtures" / "lanes"
FIXTURE = FIXTURES / "slop-hygiene.md"
FIXTURE_SWEEP = FIXTURES / "unscoped-sweep.md"


def test_generated_schema_closes_rule_enum() -> None:
    lane = load_lane(FIXTURE)
    schema = lane.output_schema()
    props = schema["properties"]["findings"]["items"]["properties"]
    assert set(props["rule_id"]["enum"]) == set(lane.rules) | {"slop/other"}


def test_severity_cap_removes_higher_levels() -> None:
    lane = load_lane(FIXTURE_SWEEP)
    schema = lane.output_schema()
    severity = schema["properties"]["findings"]["items"]["properties"]["severity"]["enum"]
    assert "blocker" not in severity


def test_other_rule_is_always_appended() -> None:
    lane = load_lane(FIXTURE)
    prefix = lane.rules[0].split("/")[0]
    assert (
        f"{prefix}/other"
        in lane.output_schema()["properties"]["findings"]["items"]["properties"]["rule_id"]["enum"]
    )


def test_runtime_finding_requires_only_runtime_fields() -> None:
    lane = load_lane(FIXTURE)
    finding_schema = lane.output_schema()["properties"]["findings"]["items"]
    assert finding_schema["required"] == ["rule_id", "file", "line", "severity", "body"]


def test_output_schema_satisfies_openai_strict_required() -> None:
    """OpenAI structured output rejects schemas whose object levels omit any
    property key from `required` (live 400: "Missing 'findings'"). Every
    object level must list ALL its properties as required."""
    lane = load_lane(FIXTURE)
    schema = lane.output_schema()

    def assert_strict(node: object) -> None:
        if isinstance(node, dict):
            node_d = cast(dict[str, object], node)
            props = node_d.get("properties")
            if node_d.get("type") == "object" and isinstance(props, dict):
                props_d = cast(dict[str, object], props)
                required = node_d.get("required")
                required_l = cast(list[str], required) if isinstance(required, list) else []
                assert set(required_l) == set(props_d), (
                    f"strict-required violation at object with keys {list(props_d)}"
                )
            for value in node_d.values():
                assert_strict(value)
        elif isinstance(node, list):
            for item in cast(list[object], node):
                assert_strict(item)

    assert_strict(schema)


def test_validation_lifecycle_field() -> None:
    lane = load_lane(FIXTURE)
    assert lane.validation is None  # fixture pre-dates the sample gate


def test_lane_scope_and_brief_requirement_default_compatibly() -> None:
    lane = load_lane(FIXTURE)

    assert lane.scope == "repository"
    assert lane.requires_brief is False


def test_lane_accepts_explicit_scope_and_brief_requirement() -> None:
    lane = Lane(
        lane="dynamic/change-intent",
        tier="dynamic",
        rules=["dynamic/intent"],
        prompt_body="Review the stated intent.",
        scope="direct-deps",
        requires_brief=True,
    )

    assert lane.scope == "direct-deps"
    assert lane.requires_brief is True
