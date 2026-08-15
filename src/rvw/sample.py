"""Closed-enum versus free-rule-id sampling gate (ADR-004)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from rvw.diffbudget import apply_diff_budget, require_reviewable_diff
from rvw.dispatch import DEFAULT_CONCURRENCY, DEFAULT_DEADLINE_SECONDS
from rvw.hostslots import HostSlotGate, host_slot
from rvw.lane import Lane
from rvw.prompts import build_chunk_context, build_lane_prompt
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.runtimes.codex import validate_output
from rvw.schema import RuntimeLaneOutput


def free_variant_schema(lane: Lane) -> dict[str, Any]:
    """Return the lane schema with only the closed rule-id enum relaxed."""

    schema = lane.output_schema()
    schema["properties"]["findings"]["items"]["properties"]["rule_id"] = {"type": "string"}
    return schema


def validate_output_free(raw: object) -> RuntimeLaneOutput:
    """Validate lane output without applying lane rule-id membership."""

    return RuntimeLaneOutput.model_validate(raw)


@dataclass(frozen=True)
class SampleSiteVariance:
    variant: Literal["enum_only", "free_only"]
    rule_id: str
    file: str
    line: int | None


@dataclass(frozen=True)
class SampleReport:
    lane_id: str
    enum_findings: list[tuple[str, int | None]]
    free_findings: list[tuple[str, int | None]]
    enum_only: list[tuple[str, int | None]]
    free_only: list[tuple[str, int | None]]
    novel_rule_ids: list[str]
    site_variance: list[SampleSiteVariance]
    verdict: Literal["PASS", "REVIEW"]
    replicas: int
    chunk_count: int


def _sites(
    results: list[RunResult[Any]],
) -> dict[tuple[str, int | None], tuple[str, int | None]]:
    sites: dict[tuple[str, int | None], tuple[str, int | None]] = {}
    for result in results:
        if result.status is not RunStatus.VALID or result.output is None:
            continue
        output = cast(RuntimeLaneOutput, result.output)
        for finding in output.findings:
            sites.setdefault((finding.file, finding.line), (finding.rule_id, finding.line))
    return sites


def _ordered_values(
    sites: dict[tuple[str, int | None], tuple[str, int | None]],
    selected: set[tuple[str, int | None]] | None = None,
) -> list[tuple[str, int | None]]:
    keys = sites.keys() if selected is None else selected
    return [
        sites[key]
        for key in sorted(keys, key=lambda item: (item[0], item[1] is None, item[1] or 0))
    ]


def _rule_ids(results: list[RunResult[Any]]) -> set[str]:
    rule_ids: set[str] = set()
    for result in results:
        if result.status is not RunStatus.VALID or result.output is None:
            continue
        output = cast(RuntimeLaneOutput, result.output)
        rule_ids.update(finding.rule_id for finding in output.findings)
    return rule_ids


def _site_variance(
    *,
    enum_sites: dict[tuple[str, int | None], tuple[str, int | None]],
    free_sites: dict[tuple[str, int | None], tuple[str, int | None]],
    closed_rule_ids: set[str],
) -> list[SampleSiteVariance]:
    variance: list[SampleSiteVariance] = []
    for variant, sites, selected in (
        ("enum_only", enum_sites, set(enum_sites) - set(free_sites)),
        ("free_only", free_sites, set(free_sites) - set(enum_sites)),
    ):
        for file, line in sorted(
            selected, key=lambda item: (item[0], item[1] is None, item[1] or 0)
        ):
            rule_id = sites[(file, line)][0]
            if rule_id in closed_rule_ids:
                variance.append(
                    SampleSiteVariance(
                        variant=variant,
                        rule_id=rule_id,
                        file=file,
                        line=line,
                    )
                )
    return variance


async def sample_lane(
    lane: Lane,
    *,
    fixture_diff: str,
    runtime: Runtime,
    out_root: Path,
    replicas: int = 3,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    concurrency: int = DEFAULT_CONCURRENCY,
    host_gate: HostSlotGate | None = None,
) -> SampleReport:
    """Run enum and free-schema variants and separate rule gaps from site variance."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")
    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    chunks, budget = apply_diff_budget(fixture_diff)
    require_reviewable_diff(budget, source="fixture")
    prompts = {
        chunk.index: build_lane_prompt(
            lane,
            diff=chunk.text,
            brief=None,
            brief_source=None,
            covered_rules={},
            chunk_context=build_chunk_context(
                chunk=chunk.index,
                chunk_count=len(chunks),
                chunk_files=chunk.files,
                kept_files=budget.kept_files,
            ),
        )
        for chunk in chunks
    }
    semaphore = asyncio.Semaphore(concurrency)

    def validate_enum(raw: object) -> RuntimeLaneOutput:
        return validate_output(lane, raw)

    async def execute_one(
        variant: Literal["enum", "free"], replica: int, chunk: int
    ) -> RunResult[Any]:
        async with semaphore:
            if variant == "enum":
                schema = lane.output_schema()
                validator = validate_enum
            else:
                schema = free_variant_schema(lane)
                validator = validate_output_free
            variant_dir = out_root / variant
            if len(chunks) > 1:
                variant_dir /= f"c{chunk}"
            async with host_slot(host_gate):
                return replace(
                    await runtime.execute_raw(
                        schema=schema,
                        prompt=prompts[chunk],
                        run_dir=variant_dir / f"r{replica}",
                        deadline_seconds=deadline_seconds,
                        validate=validator,
                    ),
                    chunk=chunk,
                )

    tasks = [
        asyncio.create_task(execute_one(variant, replica, chunk.index))
        for variant in ("enum", "free")
        for chunk in chunks
        for replica in range(1, replicas + 1)
    ]
    all_results = await asyncio.gather(*tasks)
    runs_per_variant = replicas * len(chunks)
    enum_results = all_results[:runs_per_variant]
    free_results = all_results[runs_per_variant:]
    enum_sites = _sites(enum_results)
    free_sites = _sites(free_results)
    enum_only_sites = set(enum_sites) - set(free_sites)
    free_only_sites = set(free_sites) - set(enum_sites)
    rule_schema = lane.output_schema()["properties"]["findings"]["items"]["properties"]["rule_id"]
    closed_rule_ids = set(cast(list[str], rule_schema["enum"]))
    novel_rule_ids = sorted(_rule_ids(free_results) - closed_rule_ids)
    return SampleReport(
        lane_id=lane.id,
        enum_findings=_ordered_values(enum_sites),
        free_findings=_ordered_values(free_sites),
        enum_only=_ordered_values(enum_sites, enum_only_sites),
        free_only=_ordered_values(free_sites, free_only_sites),
        novel_rule_ids=novel_rule_ids,
        site_variance=_site_variance(
            enum_sites=enum_sites,
            free_sites=free_sites,
            closed_rule_ids=closed_rule_ids,
        ),
        verdict="REVIEW" if novel_rule_ids else "PASS",
        replicas=replicas,
        chunk_count=len(chunks),
    )


__all__ = [
    "SampleReport",
    "SampleSiteVariance",
    "free_variant_schema",
    "sample_lane",
    "validate_output_free",
]
