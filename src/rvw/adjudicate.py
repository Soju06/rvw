"""Evidence-bearing, majority-voted adjudication of merged findings."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rvw.diffbudget import reviewed_diff
from rvw.dispatch import DEFAULT_CONCURRENCY, DEFAULT_DEADLINE_SECONDS
from rvw.hostslots import HostSlotGate, host_slot
from rvw.merge import CollapseGroup, MergeResult
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.schema import RuntimeAdjudication, RuntimeAdjudicationItem, Verdict
from rvw.target import ResolvedTarget


def adjudication_schema(group_keys: Sequence[str]) -> dict[str, Any]:
    """Build the closed, OpenAI-strict schema for one candidate batch."""

    schema = RuntimeAdjudication.model_json_schema()
    schema.pop("$defs", None)
    item_properties = dict(RuntimeAdjudicationItem.model_json_schema()["properties"])
    item_properties["group_key"] = {"type": "string", "enum": list(group_keys)}
    item_properties["verdict"] = {
        "type": "string",
        "enum": [verdict.value for verdict in Verdict],
    }
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"])
    schema["properties"]["items"]["items"] = {
        "type": "object",
        "properties": item_properties,
        "required": list(item_properties),
        "additionalProperties": False,
    }
    return schema


def build_adjudication_prompt(
    groups: Sequence[CollapseGroup],
    *,
    diff: str,
    expanded: bool,
    retry_invalid_reasons: Sequence[str] = (),
) -> str:
    """Render an adjudication-only prompt with every replica body preserved."""

    role = (
        "You are an adjudicator, not a reviewer. For each candidate finding, decide from "
        "the ACTUAL SOURCE in this working directory whether it is real. Do not report new findings."
        if expanded
        else "You are an adjudicator, not a reviewer. For each candidate finding, decide from "
        "the supplied candidate bodies and unified diff. Do not report new findings."
    )
    parts = [
        "# Role",
        role,
        "# Verdict contract",
        (
            "CONFIRMED = the defect is real at HEAD; evidence must quote the offending source "
            "line(s) verbatim."
        ),
        (
            "REJECTED = the claim is factually wrong; evidence MUST quote the disproving source "
            "line(s) verbatim."
        ),
        "UNCERTAIN = you cannot decide from the available context.",
        (
            "Never guess: an unverifiable claim is UNCERTAIN, not REJECTED. Return exactly one "
            "verdict for each supplied candidate and no other findings."
        ),
    ]
    if expanded:
        parts.extend(
            [
                "# Expanded context",
                (
                    "EXPANDED CONTEXT PASS: you may and should explore beyond the diff — read "
                    "the full enclosing function/class, find the symbol's definition and its "
                    "callers (grep), and check tests covering the path, before deciding. Prior "
                    "pass returned UNCERTAIN for these."
                ),
            ]
        )
    else:
        parts.extend(
            [
                "## Evidence boundary",
                (
                    "The supplied candidate bodies and unified diff are the complete evidence for "
                    "this initial pass. Do not inspect the working directory or use tools. Return "
                    "UNCERTAIN when they cannot establish the verdict."
                ),
            ]
        )

    if retry_invalid_reasons:
        parts.extend(
            [
                "# Retry feedback",
                (
                    "The previous wave produced no valid outputs. Correct the "
                    "machine-readable failures below while returning the same batch."
                ),
                *[f"- {reason}" for reason in retry_invalid_reasons],
            ]
        )

    parts.append("# Candidates")
    for group in groups:
        parts.extend(
            [
                f"## Candidate {group.key}",
                f"group_key: {group.key}",
                f"rule_id: {group.rule_id}",
                f"location: {group.file}:{group.line if group.line is not None else 'unknown'}",
                "Replica reports (verbatim):",
            ]
        )
        for index, body in enumerate(group.bodies, start=1):
            parts.extend([f"### Body {index}", body])

    parts.extend(["# Unified diff", "```diff", diff, "```"])
    return "\n\n".join(parts)


class AdjudicationOutcome(BaseModel):
    """Strict persisted adjudication outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdicts: dict[str, Verdict]
    reasons: dict[str, str]
    evidence: dict[str, str]
    replica_votes: dict[str, list[Verdict]]
    unresolved: list[str]
    coerced_rejections: int = Field(ge=0)

    @model_validator(mode="after")
    def _uncertain_verdicts_require_reasons(self) -> AdjudicationOutcome:
        for key, verdict in self.verdicts.items():
            if verdict is Verdict.UNCERTAIN and not self.reasons.get(key, "").strip():
                raise ValueError(f"UNCERTAIN verdict {key!r} requires a non-empty reason")
        return self


class AdjudicationAttempt(BaseModel):
    """One invalid runtime attempt retained in an infrastructure error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wave: str
    replica: int = Field(ge=1)
    reason: str
    artifact_dir: str
    exit_code: int | None = None
    detail: str | None = None
    log_path: str | None = None
    log_bytes: int | None = Field(default=None, ge=0)
    output_path: str | None = None
    output_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _reason_must_not_be_blank(self) -> AdjudicationAttempt:
        if not self.reason.strip():
            raise ValueError("adjudication attempt reason must not be blank")
        return self


class AdjudicationInfrastructureError(RuntimeError):
    """A required adjudication pass exhausted its retry without valid output."""

    def __init__(self, pass_name: str, attempts: Sequence[AdjudicationAttempt]) -> None:
        self.pass_name = pass_name
        self.attempts = list(attempts)
        self.outcome = None
        reasons = ", ".join(sorted({attempt.reason for attempt in attempts}))
        super().__init__(
            f"no valid adjudication output for {pass_name} pass after retry"
            + (f" ({reasons})" if reasons else "")
        )


@dataclass(frozen=True)
class _Vote:
    verdict: Verdict
    reason: str
    evidence: str


@dataclass(frozen=True)
class _BatchVote:
    verdicts: dict[str, Verdict]
    reasons: dict[str, str]
    evidence: dict[str, str]
    replica_votes: dict[str, list[Verdict]]
    coerced_rejections: int


def _adjudication_attempt(result: RunResult[Any]) -> AdjudicationAttempt:
    diagnostic = result.diagnostic
    log_path = result.artifact_dir / "run.log"
    output_path = result.artifact_dir / "out.json"
    return AdjudicationAttempt(
        wave=result.artifact_dir.parent.name,
        replica=result.replica,
        reason=result.invalid_reason or "unknown",
        artifact_dir=str(result.artifact_dir),
        exit_code=diagnostic.exit_code if diagnostic is not None else None,
        detail=diagnostic.detail if diagnostic is not None else None,
        log_path=(
            diagnostic.log_path
            if diagnostic is not None and diagnostic.log_path is not None
            else str(log_path)
        ),
        log_bytes=(
            diagnostic.log_bytes
            if diagnostic is not None
            else (log_path.stat().st_size if log_path.is_file() else None)
        ),
        output_path=(
            diagnostic.output_path
            if diagnostic is not None and diagnostic.output_path is not None
            else str(output_path)
        ),
        output_bytes=(
            diagnostic.output_bytes
            if diagnostic is not None
            else (output_path.stat().st_size if output_path.is_file() else None)
        ),
    )


def _vote_batch(groups: Sequence[CollapseGroup], results: Sequence[RunResult[Any]]) -> _BatchVote:
    valid_outputs = [
        cast(RuntimeAdjudication, result.output)
        for result in results
        if result.status is RunStatus.VALID and result.output is not None
    ]
    votes_by_key: dict[str, list[_Vote]] = {group.key: [] for group in groups}
    coerced_rejections = 0
    for output in valid_outputs:
        by_key: dict[str, RuntimeAdjudicationItem] = {}
        for adjudication_item in output.items:
            by_key.setdefault(adjudication_item.group_key, adjudication_item)
        for group in groups:
            adjudication_item = by_key.get(group.key)
            if adjudication_item is None:
                votes_by_key[group.key].append(
                    _Vote(Verdict.UNCERTAIN, "adjudicator omitted this candidate", "")
                )
                continue
            verdict = adjudication_item.verdict
            reason = adjudication_item.reason
            if verdict is Verdict.REJECTED and not adjudication_item.evidence.strip():
                verdict = Verdict.UNCERTAIN
                reason = "REJECTED vote lacked required evidence"
                coerced_rejections += 1
            votes_by_key[group.key].append(_Vote(verdict, reason, adjudication_item.evidence))

    verdicts: dict[str, Verdict] = {}
    reasons: dict[str, str] = {}
    evidence: dict[str, str] = {}
    replica_votes: dict[str, list[Verdict]] = {}
    for group in groups:
        group_votes = votes_by_key[group.key]
        replica_votes[group.key] = [vote.verdict for vote in group_votes]
        counts = Counter(vote.verdict for vote in group_votes)
        verdict = Verdict.UNCERTAIN
        for candidate in Verdict:
            if counts[candidate] > len(group_votes) / 2:
                verdict = candidate
                break
        verdicts[group.key] = verdict
        supporting_vote = next((vote for vote in group_votes if vote.verdict is verdict), None)
        if verdict is Verdict.UNCERTAIN and supporting_vote is None:
            reasons[group.key] = "no strict majority across valid adjudication replicas"
        else:
            reasons[group.key] = supporting_vote.reason if supporting_vote is not None else ""
        evidence[group.key] = supporting_vote.evidence if supporting_vote is not None else ""

    return _BatchVote(
        verdicts=verdicts,
        reasons=reasons,
        evidence=evidence,
        replica_votes=replica_votes,
        coerced_rejections=coerced_rejections,
    )


async def adjudicate(
    merged: MergeResult,
    *,
    target: ResolvedTarget,
    runtime: Runtime,
    repo_dir: Path,
    out_root: Path,
    replicas: int = 3,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    concurrency: int = DEFAULT_CONCURRENCY,
    host_gate: HostSlotGate | None = None,
    expanded_runtime: Runtime | None = None,
) -> AdjudicationOutcome:
    """Adjudicate all collapse groups, widening context once for uncertainty."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")
    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if not merged.groups:
        return AdjudicationOutcome(
            verdicts={},
            reasons={},
            evidence={},
            replica_votes={},
            unresolved=[],
            coerced_rejections=0,
        )
    expanded_runtime = expanded_runtime or runtime

    semaphore = asyncio.Semaphore(concurrency)
    reviewed = reviewed_diff(target.diff)

    async def execute_wave(
        groups: Sequence[CollapseGroup],
        *,
        expanded: bool,
        label: str,
        deadline: int,
        pass_runtime: Runtime,
        retry_invalid_reasons: Sequence[str] = (),
    ) -> list[RunResult[Any]]:
        prompt = build_adjudication_prompt(
            groups,
            diff=reviewed.text,
            expanded=expanded,
            retry_invalid_reasons=retry_invalid_reasons,
        )
        schema = adjudication_schema([group.key for group in groups])

        async def execute_one(replica: int) -> RunResult[Any]:
            async with semaphore:
                run_dir = out_root / label / f"r{replica}"
                async with host_slot(host_gate):
                    return await pass_runtime.execute_raw(
                        schema=schema,
                        prompt=prompt,
                        run_dir=run_dir,
                        deadline_seconds=deadline,
                        workdir=repo_dir,
                        validate=RuntimeAdjudication.model_validate,
                    )

        return list(
            await asyncio.gather(
                *(asyncio.create_task(execute_one(replica)) for replica in range(1, replicas + 1))
            )
        )

    async def execute_pass(
        groups: Sequence[CollapseGroup], *, expanded: bool, label: str, deadline: int
    ) -> list[RunResult[Any]]:
        pass_runtime = expanded_runtime if expanded else runtime
        results = await execute_wave(
            groups,
            expanded=expanded,
            label=label,
            deadline=deadline,
            pass_runtime=pass_runtime,
        )
        if all(result.status is RunStatus.INVALID for result in results):
            retry_invalid_reasons = [
                f"replica {result.replica}: {result.invalid_reason or 'unknown_invalid'}"
                for result in results
            ]
            retry_results = await execute_wave(
                groups,
                expanded=expanded,
                label=f"{label}-retry",
                deadline=deadline,
                pass_runtime=pass_runtime,
                retry_invalid_reasons=retry_invalid_reasons,
            )
            if all(result.status is RunStatus.INVALID for result in retry_results):
                attempts = [_adjudication_attempt(result) for result in [*results, *retry_results]]
                raise AdjudicationInfrastructureError(label, attempts)
            return retry_results
        return results

    initial_results = await execute_pass(
        merged.groups,
        expanded=False,
        label="initial",
        deadline=deadline_seconds,
    )
    initial = _vote_batch(merged.groups, initial_results)
    verdicts = dict(initial.verdicts)
    reasons = dict(initial.reasons)
    evidence = dict(initial.evidence)
    replica_votes = {key: list(votes) for key, votes in initial.replica_votes.items()}
    coerced_rejections = initial.coerced_rejections

    uncertain_groups = [
        group for group in merged.groups if verdicts[group.key] is Verdict.UNCERTAIN
    ]
    if uncertain_groups:
        expanded_results = await execute_pass(
            uncertain_groups,
            expanded=True,
            label="expanded",
            deadline=deadline_seconds * 2,
        )
        expanded_vote = _vote_batch(uncertain_groups, expanded_results)
        coerced_rejections += expanded_vote.coerced_rejections
        for group in uncertain_groups:
            verdicts[group.key] = expanded_vote.verdicts[group.key]
            reasons[group.key] = expanded_vote.reasons[group.key]
            evidence[group.key] = expanded_vote.evidence[group.key]
            replica_votes[group.key] = expanded_vote.replica_votes[group.key]

    unresolved = [group.key for group in merged.groups if verdicts[group.key] is Verdict.UNCERTAIN]
    return AdjudicationOutcome(
        verdicts=verdicts,
        reasons=reasons,
        evidence=evidence,
        replica_votes=replica_votes,
        unresolved=unresolved,
        coerced_rejections=coerced_rejections,
    )


__all__ = [
    "AdjudicationAttempt",
    "AdjudicationInfrastructureError",
    "AdjudicationOutcome",
    "adjudicate",
    "adjudication_schema",
    "build_adjudication_prompt",
]
