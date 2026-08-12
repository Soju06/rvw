"""Batched source-grounded presence adjudication for stack finding lineages."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from rvw.dispatch import DEFAULT_CONCURRENCY
from rvw.hostslots import HostSlotGate, host_slot
from rvw.runtimes import RunResult, RunStatus, Runtime
from rvw.stack import FindingLineage, Presence, PresenceObservation
from rvw.target import ResolvedTarget


class RuntimePresenceItem(BaseModel):
    """One runtime vote about an existing origin claim at a descendant head."""

    model_config = ConfigDict(extra="forbid")

    lineage_id: str
    presence: Presence
    reason: str
    evidence: str


class RuntimePresence(BaseModel):
    """Strict runtime output for one batched descendant recheck."""

    model_config = ConfigDict(extra="forbid")

    items: list[RuntimePresenceItem]


@dataclass(frozen=True)
class PresenceOutcome:
    observations: dict[str, PresenceObservation]
    unresolved: list[str]
    coerced_evidence: int


@dataclass(frozen=True)
class _Vote:
    presence: Presence
    reason: str
    evidence: str


@dataclass(frozen=True)
class _BatchVote:
    presence: dict[str, Presence]
    reasons: dict[str, str]
    evidence: dict[str, str]
    replica_votes: dict[str, list[Presence]]
    coerced_evidence: int


def presence_schema(lineage_ids: Sequence[str]) -> dict[str, Any]:
    """Build a closed OpenAI-strict schema for supplied lineage IDs only."""

    schema = RuntimePresence.model_json_schema()
    schema.pop("$defs", None)
    item_properties = dict(RuntimePresenceItem.model_json_schema()["properties"])
    item_properties["lineage_id"] = {
        "type": "string",
        "enum": list(lineage_ids),
    }
    item_properties["presence"] = {
        "type": "string",
        "enum": [presence.value for presence in Presence],
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


def validate_presence_output(
    raw: object,
    *,
    lineage_ids: Sequence[str],
) -> RuntimePresence:
    """Validate the static model plus the batch-specific lineage enum."""

    output = RuntimePresence.model_validate(raw)
    output_ids = [item.lineage_id for item in output.items]
    if len(output_ids) != len(set(output_ids)):
        raise ValueError("presence output contains duplicate lineage_id values")
    allowed = set(lineage_ids)
    if any(item.lineage_id not in allowed for item in output.items):
        raise ValueError("presence output lineage_id is outside the supplied batch")
    return output


def _batch_lineage_ids(lineages: Sequence[FindingLineage]) -> dict[str, str]:
    lineage_ids = [lineage.lineage_id for lineage in lineages]
    if len(lineage_ids) != len(set(lineage_ids)):
        raise ValueError("presence lineage IDs must be unique")
    return {lineage_id: f"L{index}" for index, lineage_id in enumerate(lineage_ids, start=1)}


def build_presence_prompt(
    lineages: Sequence[FindingLineage],
    *,
    target: ResolvedTarget,
    expanded: bool,
    retry_invalid_reasons: Sequence[str] = (),
) -> str:
    """Render immutable origin claims for verification at one descendant HEAD."""

    parts = [
        "# Role",
        (
            "You are checking previously reported defects against the ACTUAL SOURCE at the "
            "current stacked-PR HEAD. Do not review the current PR and do not report new "
            "findings. Return exactly one item for every supplied lineage."
        ),
        "# Presence contract",
        (
            "PRESENT = the original defect claim still exists at this HEAD. Quote the current "
            "source that proves it in evidence."
        ),
        (
            "ABSENT = the original defect claim no longer exists at this HEAD. Quote the "
            "current source that disproves or fixes it in evidence."
        ),
        "UNCERTAIN = current source is insufficient to decide. Never infer ABSENT from moved code.",
        f"# Descendant PR\nPR #{target.pr_number} at `{target.head_sha}`",
    ]
    if expanded:
        parts.extend(
            [
                "# Expanded context",
                (
                    "EXPANDED CONTEXT PASS: inspect enclosing definitions, referenced symbols, "
                    "callers, and relevant tests before deciding. The prior pass was UNCERTAIN."
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
    parts.append("# Origin lineages")
    batch_ids = _batch_lineage_ids(lineages)
    for lineage in lineages:
        batch_id = batch_ids[lineage.lineage_id]
        location = f"{lineage.file}:{lineage.line if lineage.line is not None else 'unknown'}"
        parts.extend(
            [
                f"## Lineage {batch_id}",
                f"lineage_id: {batch_id}",
                f"origin: PR #{lineage.origin_pr} / run `{lineage.origin_run_id}`",
                f"origin_finding_id: {lineage.origin_finding_id}",
                f"rule_id: {lineage.rule_id}",
                f"origin_location: {location}",
                "Original reports (verbatim):",
            ]
        )
        for index, body in enumerate(lineage.bodies, start=1):
            parts.extend([f"### Body {index}", body])
    parts.extend(["# Descendant unified diff", "```diff", target.diff, "```"])
    return "\n\n".join(parts)


def _vote_batch(
    lineages: Sequence[FindingLineage],
    results: Sequence[RunResult[Any]],
) -> _BatchVote:
    valid_outputs = [
        cast(RuntimePresence, result.output)
        for result in results
        if result.status is RunStatus.VALID and result.output is not None
    ]
    votes_by_id: dict[str, list[_Vote]] = {lineage.lineage_id: [] for lineage in lineages}
    batch_ids = _batch_lineage_ids(lineages)
    coerced_evidence = 0
    for output in valid_outputs:
        output_ids = [item.lineage_id for item in output.items]
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("presence output contains duplicate lineage_id values")
        by_id = {item.lineage_id: item for item in output.items}
        for lineage in lineages:
            item = by_id.get(batch_ids[lineage.lineage_id])
            if item is None:
                votes_by_id[lineage.lineage_id].append(_Vote(Presence.UNCERTAIN, "", ""))
                continue
            presence = item.presence
            if presence is not Presence.UNCERTAIN and not item.evidence.strip():
                presence = Presence.UNCERTAIN
                coerced_evidence += 1
            votes_by_id[lineage.lineage_id].append(_Vote(presence, item.reason, item.evidence))

    presence_by_id: dict[str, Presence] = {}
    reasons: dict[str, str] = {}
    evidence: dict[str, str] = {}
    replica_votes: dict[str, list[Presence]] = {}
    for lineage in lineages:
        lineage_id = lineage.lineage_id
        votes = votes_by_id[lineage_id]
        replica_votes[lineage_id] = [vote.presence for vote in votes]
        counts = Counter(vote.presence for vote in votes)
        selected = Presence.UNCERTAIN
        for candidate in Presence:
            if counts[candidate] > len(votes) / 2:
                selected = candidate
                break
        presence_by_id[lineage_id] = selected
        supporting = next((vote for vote in votes if vote.presence is selected), None)
        reasons[lineage_id] = supporting.reason if supporting is not None else ""
        evidence[lineage_id] = supporting.evidence if supporting is not None else ""

    return _BatchVote(
        presence=presence_by_id,
        reasons=reasons,
        evidence=evidence,
        replica_votes=replica_votes,
        coerced_evidence=coerced_evidence,
    )


async def adjudicate_presence(
    lineages: Sequence[FindingLineage],
    *,
    pr_number: int,
    member_order: Sequence[int],
    target: ResolvedTarget,
    runtime: Runtime,
    repo_dir: Path,
    out_root: Path,
    replicas: int = 3,
    deadline_seconds: int = 600,
    concurrency: int = DEFAULT_CONCURRENCY,
    host_gate: HostSlotGate | None = None,
) -> PresenceOutcome:
    """Recheck all earlier lineages once at a descendant PR head."""

    if replicas < 1:
        raise ValueError("replicas must be at least 1")
    if deadline_seconds < 1:
        raise ValueError("deadline_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if target.kind != "pr" or target.pr_number != pr_number:
        raise ValueError("presence target must be the requested pull request")
    ordered_prs = list(member_order)
    if len(ordered_prs) != len(set(ordered_prs)):
        raise ValueError("presence member order must contain unique PR numbers")
    try:
        current_index = ordered_prs.index(pr_number)
    except ValueError as exc:
        raise ValueError("presence target must belong to the supplied member order") from exc
    candidates = list(lineages)
    if not candidates:
        return PresenceOutcome({}, [], 0)
    if len({lineage.lineage_id for lineage in candidates}) != len(candidates):
        raise ValueError("presence lineage IDs must be unique")
    for lineage in candidates:
        try:
            origin_index = ordered_prs.index(lineage.origin_pr)
        except ValueError as exc:
            raise ValueError("presence lineage origin must belong to the member order") from exc
        expected = ordered_prs[origin_index:current_index]
        actual = [observation.pr_number for observation in lineage.observations]
        if origin_index >= current_index or actual != expected:
            raise ValueError(
                "presence lineage observations must follow manifest order before "
                f"PR #{pr_number}: expected {expected}, found {actual}"
            )

    semaphore = asyncio.Semaphore(concurrency)

    async def execute_wave(
        selected: Sequence[FindingLineage],
        *,
        expanded: bool,
        label: str,
        deadline: int,
        retry_invalid_reasons: Sequence[str] = (),
    ) -> list[RunResult[Any]]:
        prompt = build_presence_prompt(
            selected,
            target=target,
            expanded=expanded,
            retry_invalid_reasons=retry_invalid_reasons,
        )
        lineage_ids = list(_batch_lineage_ids(selected).values())
        schema = presence_schema(lineage_ids)

        async def execute_one(replica: int) -> RunResult[Any]:
            async with semaphore:
                run_dir = out_root / label / f"r{replica}"
                async with host_slot(host_gate):
                    return await runtime.execute_raw(
                        schema=schema,
                        prompt=prompt,
                        run_dir=run_dir,
                        deadline_seconds=deadline,
                        workdir=repo_dir,
                        validate=lambda raw: validate_presence_output(
                            raw,
                            lineage_ids=lineage_ids,
                        ),
                    )

        return list(
            await asyncio.gather(
                *(asyncio.create_task(execute_one(replica)) for replica in range(1, replicas + 1))
            )
        )

    async def execute_pass(
        selected: Sequence[FindingLineage],
        *,
        expanded: bool,
        label: str,
        deadline: int,
    ) -> list[RunResult[Any]]:
        results = await execute_wave(
            selected,
            expanded=expanded,
            label=label,
            deadline=deadline,
        )
        if all(result.status is RunStatus.INVALID for result in results):
            retry_invalid_reasons = [
                f"replica {result.replica}: {result.invalid_reason or 'unknown_invalid'}"
                for result in results
            ]
            return await execute_wave(
                selected,
                expanded=expanded,
                label=f"{label}-retry",
                deadline=deadline,
                retry_invalid_reasons=retry_invalid_reasons,
            )
        return results

    initial_results = await execute_pass(
        candidates,
        expanded=False,
        label="initial",
        deadline=deadline_seconds,
    )
    initial = _vote_batch(candidates, initial_results)
    selected_presence = dict(initial.presence)
    reasons = dict(initial.reasons)
    evidence = dict(initial.evidence)
    replica_votes = {lineage_id: list(votes) for lineage_id, votes in initial.replica_votes.items()}
    coerced_evidence = initial.coerced_evidence

    uncertain = [
        lineage
        for lineage in candidates
        if selected_presence[lineage.lineage_id] is Presence.UNCERTAIN
    ]
    if uncertain:
        expanded_results = await execute_pass(
            uncertain,
            expanded=True,
            label="expanded",
            deadline=deadline_seconds * 2,
        )
        expanded_vote = _vote_batch(uncertain, expanded_results)
        coerced_evidence += expanded_vote.coerced_evidence
        for lineage in uncertain:
            lineage_id = lineage.lineage_id
            selected_presence[lineage_id] = expanded_vote.presence[lineage_id]
            reasons[lineage_id] = expanded_vote.reasons[lineage_id]
            evidence[lineage_id] = expanded_vote.evidence[lineage_id]
            replica_votes[lineage_id] = expanded_vote.replica_votes[lineage_id]

    observations = {
        lineage.lineage_id: PresenceObservation(
            pr_number=pr_number,
            presence=selected_presence[lineage.lineage_id],
            reason=reasons[lineage.lineage_id],
            evidence=evidence[lineage.lineage_id],
            replica_votes=replica_votes[lineage.lineage_id],
        )
        for lineage in candidates
    }
    unresolved = [
        lineage.lineage_id
        for lineage in candidates
        if selected_presence[lineage.lineage_id] is Presence.UNCERTAIN
    ]
    return PresenceOutcome(
        observations=observations,
        unresolved=unresolved,
        coerced_evidence=coerced_evidence,
    )


__all__ = [
    "PresenceOutcome",
    "RuntimePresence",
    "RuntimePresenceItem",
    "adjudicate_presence",
    "build_presence_prompt",
    "presence_schema",
    "validate_presence_output",
]
