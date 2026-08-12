from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

import rvw.sample as sample_module
from rvw.diffbudget import EmptyReviewDiffError
from rvw.hostslots import HostSlotGate
from rvw.lane import Lane
from rvw.runtimes import RunResult, RunStatus
from rvw.sample import SampleSiteVariance, free_variant_schema, sample_lane, validate_output_free
from rvw.schema import RuntimeFinding, RuntimeLaneOutput, Severity, Tier


def lane_fixture() -> Lane:
    return Lane(
        lane="test-lane",
        tier=Tier.BASE,
        rules=["test/one", "test/two"],
        prompt_body="Find issues.",
    )


def output(*findings: tuple[str, str, int]) -> RuntimeLaneOutput:
    return RuntimeLaneOutput(
        verdict="findings" if findings else "pass",
        findings=[
            RuntimeFinding(
                rule_id=rule_id,
                file=file,
                line=line,
                severity=Severity.WARNING,
                body=f"{file}:{line}",
            )
            for rule_id, file, line in findings
        ],
    )


def fixture_diff(*, large: bool = False) -> str:
    count = 3 if large else 1
    body = "x" * 149_900 if large else "kept"
    return "".join(
        (
            f"diff --git a/file-{index}.py b/file-{index}.py\n"
            f"--- a/file-{index}.py\n"
            f"+++ b/file-{index}.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            f"+{body}\n"
        )
        for index in range(count)
    )


class FakeRuntime:
    name = "fake"

    def __init__(
        self,
        enum_outputs: Sequence[RuntimeLaneOutput | None],
        free_outputs: Sequence[RuntimeLaneOutput | None],
    ) -> None:
        self.outputs = {"enum": list(enum_outputs), "free": list(free_outputs)}
        self.calls: list[tuple[str, Path, str]] = []
        self.call_counts = {"enum": 0, "free": 0}

    async def execute_raw(
        self,
        *,
        schema: dict[str, Any],
        prompt: str,
        run_dir: Path,
        deadline_seconds: int,
        workdir: Path | None = None,
        validate: Callable[[object], BaseModel],
    ) -> RunResult[BaseModel]:
        del schema, deadline_seconds, workdir
        variant = (
            run_dir.parent.parent.name
            if run_dir.parent.name.startswith("c")
            else run_dir.parent.name
        )
        replica = int(run_dir.name.removeprefix("r"))
        self.calls.append((variant, run_dir, prompt))
        call_index = self.call_counts[variant]
        self.call_counts[variant] = call_index + 1
        scripted = self.outputs[variant][call_index]
        if scripted is None:
            return RunResult(
                lane_id="test-lane",
                replica=replica,
                status=RunStatus.INVALID,
                output=None,
                invalid_reason="scripted invalid",
                wall_seconds=0,
                artifact_dir=run_dir,
            )
        validated = validate(scripted.model_dump())
        return RunResult(
            lane_id="test-lane",
            replica=replica,
            status=RunStatus.VALID,
            output=validated,
            invalid_reason=None,
            wall_seconds=0,
            artifact_dir=run_dir,
        )

    async def execute(self, **kwargs: object) -> RunResult:
        raise AssertionError(f"execute must not be used: {kwargs}")


def assert_strict_required(node: object) -> None:
    if isinstance(node, dict):
        node_dict = cast(dict[str, object], node)
        properties = node_dict.get("properties")
        if node_dict.get("type") == "object" and isinstance(properties, dict):
            assert set(cast(list[str], node_dict["required"])) == set(properties)
        for value in node_dict.values():
            assert_strict_required(value)
    elif isinstance(node, list):
        for value in node:
            assert_strict_required(value)


def test_free_variant_schema_relaxes_only_rule_id_enum() -> None:
    schema = free_variant_schema(lane_fixture())
    rule_schema = schema["properties"]["findings"]["items"]["properties"]["rule_id"]
    assert rule_schema == {"type": "string"}
    assert_strict_required(schema)
    validate_output_free(output(("invented/rule", "a.py", 1)).model_dump())


async def test_sample_lane_propagates_injected_host_gate_to_every_runtime_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = FakeRuntime([output()], [output()])
    gate = HostSlotGate(1, base_dir=tmp_path / "host-slots")
    seen: list[HostSlotGate | None] = []

    @asynccontextmanager
    async def recording_host_slot(received: HostSlotGate | None) -> AsyncIterator[None]:
        seen.append(received)
        yield

    monkeypatch.setattr(sample_module, "host_slot", recording_host_slot)

    await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path / "out",
        replicas=1,
        host_gate=gate,
    )

    assert len(runtime.calls) == 2
    assert seen == [gate, gate]


@pytest.mark.parametrize("replicas", [1, 3])
async def test_identical_sites_pass(replicas: int, tmp_path: Path) -> None:
    enum = [output(("test/one", "a.py", 4)) for _ in range(replicas)]
    free = [output(("test/one", "a.py", 4)) for _ in range(replicas)]
    runtime = FakeRuntime(enum, free)
    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=replicas,
    )
    assert report.verdict == "PASS"
    assert report.enum_only == []
    assert report.free_only == []
    assert report.novel_rule_ids == []
    assert report.site_variance == []
    assert len(runtime.calls) == replicas * 2
    assert len({prompt for _, _, prompt in runtime.calls}) == 1
    assert [run_dir for _variant, run_dir, _prompt in runtime.calls] == [
        tmp_path / variant / f"r{replica}"
        for variant in ("enum", "free")
        for replica in range(1, replicas + 1)
    ]


async def test_free_extra_site_requires_review(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [output(("test/one", "a.py", 4))],
        [output(("free/same", "a.py", 4), ("free/extra", "b.py", 9))],
    )
    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=1,
    )
    assert report.verdict == "REVIEW"
    assert report.free_only == [("free/extra", 9)]
    assert report.novel_rule_ids == ["free/extra", "free/same"]
    assert report.site_variance == []


async def test_novel_rule_at_shared_site_requires_review(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [output(("test/one", "a.py", 4))],
        [output(("invented/rule", "a.py", 4))],
    )

    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=1,
    )

    assert report.enum_only == []
    assert report.free_only == []
    assert report.novel_rule_ids == ["invented/rule"]
    assert report.verdict == "REVIEW"


async def test_in_enum_site_difference_is_non_failing_variance(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [output(("test/one", "a.py", 4))],
        [output(("test/one", "b.py", 9))],
    )

    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=1,
    )

    assert report.verdict == "PASS"
    assert report.novel_rule_ids == []
    assert report.site_variance == [
        SampleSiteVariance(variant="enum_only", rule_id="test/one", file="a.py", line=4),
        SampleSiteVariance(variant="free_only", rule_id="test/one", file="b.py", line=9),
    ]


async def test_generated_other_rule_is_not_novel(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [output(("test/one", "a.py", 4))],
        [output(("test/other", "b.py", 9))],
    )

    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=1,
    )

    assert report.verdict == "PASS"
    assert report.novel_rule_ids == []
    assert [item.rule_id for item in report.site_variance] == ["test/one", "test/other"]


async def test_invalid_replicas_are_ignored_in_union(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [None, output(("test/one", "a.py", 4)), None],
        [None, output(("test/one", "a.py", 4)), None],
    )
    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(),
        runtime=runtime,
        out_root=tmp_path,
        replicas=3,
    )
    assert report.verdict == "PASS"
    assert report.enum_findings == [("test/one", 4)]
    assert report.free_findings == [("test/one", 4)]


async def test_large_fixture_runs_every_variant_replica_chunk(tmp_path: Path) -> None:
    enum = [
        output(("test/one", "file-0.py", 1)),
        output(("test/two", "file-2.py", 1)),
    ]
    free = [
        output(("test/one", "file-0.py", 1)),
        output(("test/two", "file-2.py", 1)),
    ]
    runtime = FakeRuntime(enum, free)

    report = await sample_lane(
        lane_fixture(),
        fixture_diff=fixture_diff(large=True),
        runtime=runtime,
        out_root=tmp_path,
        replicas=1,
    )

    assert report.chunk_count == 2
    assert [run_dir for _variant, run_dir, _prompt in runtime.calls] == [
        tmp_path / "enum" / "c1" / "r1",
        tmp_path / "enum" / "c2" / "r1",
        tmp_path / "free" / "c1" / "r1",
        tmp_path / "free" / "c2" / "r1",
    ]
    assert [
        "chunk 1/2" in runtime.calls[0][2],
        "chunk 2/2" in runtime.calls[1][2],
        "chunk 1/2" in runtime.calls[2][2],
        "chunk 2/2" in runtime.calls[3][2],
    ] == [True, True, True, True]


async def test_oversized_single_segment_fails_before_sampling_runtime(tmp_path: Path) -> None:
    oversized = (
        "diff --git a/src/large.py b/src/large.py\n"
        "--- a/src/large.py\n"
        "+++ b/src/large.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        f"+{'x' * 767_000}\n"
    )
    runtime = FakeRuntime([output()], [output()])

    with pytest.raises(
        EmptyReviewDiffError,
        match=r"^fixture produced an empty review diff; excluded: ",
    ) as caught:
        await sample_lane(
            lane_fixture(),
            fixture_diff=oversized,
            runtime=runtime,
            out_root=tmp_path,
            replicas=1,
        )

    assert caught.value.error_code == "empty-review-diff"
    assert caught.value.excluded_reason == {"src/large.py": "oversize-file"}
    assert runtime.calls == []
