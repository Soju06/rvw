"""Command-line surface for rvw."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Never, cast

import typer
from rich.console import Console
from rich.table import Table

from rvw import __version__
from rvw.adjudicate import AdjudicationOutcome, adjudicate
from rvw.diffbudget import EmptyReviewDiffError, apply_diff_budget
from rvw.discover import DiscoverResult, resolve_lane_path
from rvw.dispatch import PlannedRun, lpt_sort_key
from rvw.doctor import DoctorReport, diagnose
from rvw.gate import (
    DispositionDocument,
    GateAnchor,
    GateInvariantError,
    GatePlan,
    GateVerdict,
    build_gate_verdict,
    github_actor_permission,
    load_dispositions,
    load_gate_plan,
    provision_checkout,
    query_pull_request,
    requires_owner_authorization,
    save_gate_plan,
    save_gate_verdict,
    validate_coverage,
    verify_pull_request,
    write_disposition_template,
)
from rvw.lane import Lane, load_lane
from rvw.pipeline import (
    PipelineArtifacts,
    coverage_totals,
    execute_pipeline,
    load_pipeline_artifacts,
    optional_outcome,
    verdict_counts,
)
from rvw.policy import evaluate, load_policy
from rvw.publish import PublishError, publish_body_review, publish_review
from rvw.registry import Registry, load_registry
from rvw.report import render_report
from rvw.runtimes.codex import CodexRuntime
from rvw.sample import SampleReport, sample_lane
from rvw.schema import Tier, Verdict, finding_schema, lane_output_schema
from rvw.stack import (
    FindingLineage,
    MemberRunRef,
    StackInvariantError,
    StackManifest,
    StackResolutionError,
    append_observation,
    origin_lineages,
    parse_pr_numbers,
    resolve_stack,
    resolved_target_for_member,
    verify_manifest,
)
from rvw.stack_adjudicate import adjudicate_presence
from rvw.stack_report import render_stack_report
from rvw.stack_store import StackRunNotFound, StackStageMissing, StackStore
from rvw.store import RunHandle, RunNotFound, RunStore, StageMissing
from rvw.target import ResolvedTarget, TargetResolutionError, resolve_target

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USER_ERROR = 2
EXIT_SYSTEM_ERROR = 3
DEFAULT_REGISTRY_ROOT = Path("~/.hermes/review").expanduser()
DEFAULT_AUTO_POLICY = Path("~/.hermes/review/policies/auto.yaml").expanduser()
_PLAN_REPLICAS = 1
DEFAULT_RUN_ROOT = Path("/tmp/rvw")

_EXAMPLES: dict[str, list[str]] = {
    "review": [
        "rvw review --target 123",
        "rvw review --target 123 --pause --dynamic-brief /tmp/brief.md",
        "rvw review --target HEAD --json",
    ],
    "plan": ["rvw plan --target 123 --json"],
    "gate": [
        "rvw gate --target 123",
        "rvw gate --run <run-id> --dispositions dispositions.yaml",
    ],
    "stack": [
        "rvw stack plan --prs 101,102,103 --json",
        "rvw stack review --prs 101,102,103",
        "rvw stack publish --run <stack-run-id>",
    ],
    "lanes": ["rvw lanes list", "rvw lanes show slop-hygiene"],
    "doctor": ["rvw doctor"],
}

app = typer.Typer(
    name="rvw",
    help="Layered, replicated, self-adjudicating code review orchestrator",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
lanes_app = typer.Typer(help="Inspect registered review lanes.", no_args_is_help=True)
stack_app = typer.Typer(help="Review an explicit stacked pull-request chain.", no_args_is_help=True)
app.add_typer(lanes_app, name="lanes")
app.add_typer(stack_app, name="stack")

_console = Console()
_error_console = Console(stderr=True)
Option = cast(Callable[..., object], typer.Option)
Argument = cast(Callable[..., object], typer.Argument)


_PipelineArtifacts = PipelineArtifacts


def _write_json(payload: Any) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _empty_review_failure(exc: EmptyReviewDiffError, *, json_output: bool) -> Never:
    if json_output:
        _write_json(exc.payload())
    else:
        _error_console.print(str(exc), markup=False)
    raise typer.Exit(EXIT_USER_ERROR) from exc


def _schema_payload() -> dict[str, Any]:
    return {
        "cli_version": __version__,
        "models": {
            "Finding": finding_schema(),
            "LaneOutput": lane_output_schema(),
        },
        "exit_codes": {
            "0": "ok",
            "1": "not_found",
            "2": "user_error",
            "3": "system_error",
        },
    }


def _stub(phase: int) -> None:
    _error_console.print(f"not implemented yet (Phase {phase})")
    raise typer.Exit(EXIT_SYSTEM_ERROR)


def _load_registry_root(root: Path) -> tuple[Registry, Path]:
    expanded = root.expanduser()
    return load_registry(expanded / "layers.yaml"), expanded / "lanes"


def _registered_lane_owners(registry: Registry) -> list[tuple[str, Tier]]:
    owners: list[tuple[str, Tier]] = []
    seen: set[str] = set()
    for layer in registry.layers:
        for lane_id in layer.lanes:
            if lane_id not in seen:
                owners.append((lane_id, layer.tier))
                seen.add(lane_id)
    return owners


def _resolve_cli_target(spec: str) -> ResolvedTarget:
    """Resolve target specs, normalizing symbolic Git revisions such as HEAD."""

    cwd = Path.cwd()
    try:
        return resolve_target(spec, cwd=cwd)
    except TargetResolutionError as target_error:
        try:
            return _resolve_local_commit(spec, cwd)
        except (OSError, subprocess.CalledProcessError) as local_error:
            raise target_error from local_error
    except ValueError as direct_error:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--verify", f"{spec}^{{commit}}"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as git_error:
            raise ValueError(f"unsupported target specification: {spec!r}") from git_error
        resolved_spec = completed.stdout.strip()
        if not resolved_spec:
            raise ValueError(f"could not resolve target specification: {spec!r}") from direct_error
        try:
            return resolve_target(resolved_spec, cwd=cwd)
        except TargetResolutionError:
            return _resolve_local_commit(resolved_spec, cwd)


def _git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _resolve_local_commit(spec: str, cwd: Path) -> ResolvedTarget:
    """Resolve a commit in a local-only repository with no GitHub remote."""

    ancestry = _git_output(["rev-list", "--parents", "-n", "1", spec], cwd).split()
    if not ancestry:
        raise ValueError(f"could not resolve local commit: {spec!r}")
    root = Path(_git_output(["rev-parse", "--show-toplevel"], cwd).strip())
    names = _git_output(["show", spec, "--format=", "--name-only"], cwd)
    return ResolvedTarget(
        kind="commit",
        repo=root.name,
        base_sha=ancestry[1] if len(ancestry) > 1 else None,
        head_sha=ancestry[0],
        changed_paths=[line for line in names.splitlines() if line],
        diff=_git_output(["show", spec, "--format="], cwd),
    )


def _load_active_lanes(registry: Registry, lanes_root: Path, target: ResolvedTarget) -> list[Lane]:
    lanes: list[Lane] = []
    seen: set[str] = set()
    for layer in registry.activate(target.repo, target.changed_paths):
        for lane_id in layer.lanes:
            if lane_id not in seen:
                lanes.append(load_lane(resolve_lane_path(lanes_root, lane_id, layer.tier)))
                seen.add(lane_id)
    return lanes


def _gate_plan(registry_root: Path, target: ResolvedTarget, replicas: int) -> GatePlan:
    registry, lanes_root = _load_registry_root(registry_root)
    lane_ids = [lane.id for lane in _load_active_lanes(registry, lanes_root, target)]
    if not lane_ids:
        raise GateInvariantError("activated gate plan must contain at least one lane")
    chunks, _budget = apply_diff_budget(target.diff)
    return GatePlan(
        lane_ids=lane_ids,
        replicas=replicas,
        chunk_count=len(chunks),
    )


def _brief_source(target: ResolvedTarget, dynamic_brief: Path | None) -> str | None:
    if dynamic_brief is not None:
        return "operator"
    if target.pr_title is not None or target.pr_body is not None:
        return "pr_body"
    return None


def _plan_payload(
    registry: Registry,
    lanes_root: Path,
    target: ResolvedTarget,
    dynamic_brief: Path | None,
) -> dict[str, Any]:
    active_layers = registry.activate(target.repo, target.changed_paths)
    lanes = _load_active_lanes(registry, lanes_root, target)
    chunks, _budget = apply_diff_budget(target.diff)
    runs = [
        PlannedRun(
            lane=lane,
            prompt="",
            replica=replica,
            chunk=chunk.index,
            chunk_count=len(chunks),
        )
        for lane in lanes
        for chunk in chunks
        for replica in range(1, _PLAN_REPLICAS + 1)
    ]
    ordered_runs = sorted(runs, key=lambda run: lpt_sort_key(run.lane.cost))
    return {
        "target": {
            "kind": target.kind,
            "repo": target.repo,
            "head_sha": target.head_sha,
            "pr_number": target.pr_number,
        },
        "layers": [
            {
                "id": layer.id,
                "tier": layer.tier.value,
                "predicate": (
                    layer.when.model_dump(exclude_none=True) if layer.when is not None else None
                ),
            }
            for layer in active_layers
        ],
        "lanes": [
            {
                "lane": lane.id,
                "tier": lane.tier.value,
                "cost": lane.cost,
                "rules_count": len(lane.rules),
                "replicas": _PLAN_REPLICAS,
            }
            for lane in lanes
        ],
        "dispatch_order": [run.lane.id for run in ordered_runs],
        "chunk_count": len(chunks),
        "total_runs": len(runs),
        "brief_source": _brief_source(target, dynamic_brief),
    }


def _print_plan(payload: dict[str, Any]) -> None:
    target = cast(dict[str, object], payload["target"])
    _console.print(
        f"Target: {target['kind']} {target['repo']} @ {target['head_sha']}", soft_wrap=True
    )
    layers_table = Table(title="Activated layers")
    layers_table.add_column("Layer")
    layers_table.add_column("Tier")
    layers_table.add_column("Predicate")
    for layer_value in cast(list[dict[str, object]], payload["layers"]):
        predicate = layer_value["predicate"]
        layers_table.add_row(
            str(layer_value["id"]),
            str(layer_value["tier"]),
            json.dumps(predicate) if predicate is not None else "unconditional",
        )
    _console.print(layers_table)
    table = Table(title="Review plan")
    table.add_column("Lane")
    table.add_column("Tier")
    table.add_column("Cost")
    table.add_column("Rules", justify="right")
    table.add_column("Replicas", justify="right")
    for lane_value in cast(list[dict[str, object]], payload["lanes"]):
        table.add_row(
            str(lane_value["lane"]),
            str(lane_value["tier"]),
            str(lane_value["cost"]),
            str(lane_value["rules_count"]),
            str(lane_value["replicas"]),
        )
    _console.print(table)
    _console.print(f"Chunks: {payload['chunk_count']}")
    _console.print(f"Total runs: {payload['total_runs']}")


def _version_callback(value: bool) -> bool:
    if value:
        _console.print(f"rvw {__version__}")
        raise typer.Exit(EXIT_OK)
    return value


def _schema_callback(value: bool) -> bool:
    if value:
        _write_json(_schema_payload())
        raise typer.Exit(EXIT_OK)
    return value


def _examples_callback(value: str | None) -> str | None:
    if value is None:
        return value
    if value == "":
        _write_json(_EXAMPLES)
        raise typer.Exit(EXIT_OK)
    if value not in _EXAMPLES:
        _error_console.print(f"unknown verb: {value}")
        raise typer.Exit(EXIT_USER_ERROR)
    _write_json({value: _EXAMPLES[value]})
    raise typer.Exit(EXIT_OK)


@app.callback()
def main(
    version: Annotated[
        bool,
        Option(
            "--version",
            help="Show the rvw version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    show_schema: Annotated[
        bool,
        Option(
            "--schema",
            help="Show CLI and model schemas as JSON.",
            callback=_schema_callback,
            is_eager=True,
        ),
    ] = False,
    examples: Annotated[
        str | None,
        Option(
            "--examples",
            metavar="VERB",
            help="Show examples as JSON.",
            callback=_examples_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    pass


@app.command()
def review(
    target: Annotated[str, Option("--target")],
    repo_dir: Annotated[
        Path | None,
        Option(
            "--repo-dir",
            help="Provisioned checkout used for adjudication (operator-owned in Phase 4).",
        ),
    ] = None,
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
    replicas: Annotated[int, Option("--replicas", min=1)] = 1,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
    json_output: Annotated[bool, Option("--json")] = False,
    pause: Annotated[bool, Option("--pause")] = False,
    publish: Annotated[bool, Option("--publish")] = False,
    dynamic_brief: Annotated[Path | None, Option("--dynamic-brief")] = None,
) -> None:
    try:
        asyncio.run(
            _review_pipeline(
                target_spec=target,
                repo_dir=repo_dir,
                registry_root=registry_root,
                replicas=replicas,
                out_root=out_root,
                json_output=json_output,
                pause=pause,
                publish=publish,
                dynamic_brief=dynamic_brief,
            )
        )
    except EmptyReviewDiffError as exc:
        _empty_review_failure(exc, json_output=json_output)


def _optional_outcome(run: RunHandle) -> AdjudicationOutcome | None:
    return optional_outcome(run)


def _coverage_totals(discovered: DiscoverResult) -> dict[str, int]:
    return coverage_totals(discovered)


def _verdict_counts(outcome: AdjudicationOutcome | None) -> dict[str, int]:
    return verdict_counts(outcome)


async def _review_pipeline(
    *,
    target_spec: str,
    repo_dir: Path | None,
    registry_root: Path,
    replicas: int,
    out_root: Path,
    json_output: bool,
    pause: bool,
    publish: bool,
    dynamic_brief: Path | None,
) -> None:
    resolved_target: ResolvedTarget | None = None
    if publish:
        resolved_target = _resolve_cli_target(target_spec)
        if resolved_target.kind != "pr":
            _error_console.print("--publish requires a PR target", markup=False)
            raise typer.Exit(EXIT_USER_ERROR)
    artifacts = await _execute_pipeline(
        target_spec=target_spec,
        repo_dir=repo_dir,
        registry_root=registry_root,
        replicas=replicas,
        out_root=out_root,
        pause=pause,
        dynamic_brief=dynamic_brief,
        resolved_target=resolved_target,
    )
    if artifacts is None:
        return

    publication_url: str | None = None
    payload_path: Path | None = None
    if artifacts.target.kind == "pr" and artifacts.target.pr_number is not None:
        publication = publish_review(
            run=artifacts.run,
            repo=artifacts.target.repo,
            pr_number=artifacts.target.pr_number,
            report_md=artifacts.report_md,
            merged=artifacts.merged,
            outcome=artifacts.outcome,
            execute=publish,
        )
        publication_url = publication.review_url
        if not publish:
            payload_path = artifacts.run.dir / "publish-payload.json"

    if json_output:
        _write_json(
            {
                "run_id": artifacts.run.run_id,
                "report_path": str(artifacts.report_path),
                "verdict_counts": _verdict_counts(artifacts.outcome),
                "coverage_totals": _coverage_totals(artifacts.discovered),
            }
        )
        return

    _console.print(f"run id: {artifacts.run.run_id}", markup=False, soft_wrap=True)
    _console.print(f"report: {artifacts.report_path}", markup=False, soft_wrap=True)
    if payload_path is not None:
        _console.print(f"dry-run payload: {payload_path}", markup=False, soft_wrap=True)
    if publication_url is not None:
        _console.print(f"review: {publication_url}", markup=False, soft_wrap=True)


async def _execute_pipeline(
    *,
    target_spec: str,
    repo_dir: Path | None,
    registry_root: Path,
    replicas: int,
    out_root: Path,
    pause: bool,
    dynamic_brief: Path | None,
    resolved_target: ResolvedTarget | None = None,
) -> _PipelineArtifacts | None:
    """Execute and persist common review stages without publishing or rendering CLI output."""

    registry, lanes_root = _load_registry_root(registry_root)
    target = resolved_target or _resolve_cli_target(target_spec)
    active_lanes = _load_active_lanes(registry, lanes_root, target)
    return await execute_pipeline(
        registry=registry,
        lanes_root=lanes_root,
        target=target,
        runtime=CodexRuntime(),
        adjudicator=adjudicate,
        active_lanes=active_lanes,
        repo_dir=repo_dir,
        replicas=replicas,
        out_root=out_root,
        pause=pause,
        dynamic_brief=dynamic_brief,
        on_pause=lambda message: _console.print(message, markup=False),
        on_warning=lambda message: _error_console.print(message, markup=False),
    )


def _load_gate_artifacts(run_id: str, out_root: Path) -> _PipelineArtifacts:
    return load_pipeline_artifacts(run_id, out_root, require_outcome=True)


def _gate_failure_verdict(artifacts: _PipelineArtifacts, message: str) -> GateVerdict:
    target = artifacts.target
    if target.kind != "pr" or target.pr_number is None or target.base_sha is None:
        raise GateInvariantError("gate failure artifact requires a PR target")
    return GateVerdict(
        run_id=artifacts.run.run_id,
        repo=target.repo,
        pr_number=target.pr_number,
        anchor=GateAnchor(base_sha=target.base_sha, head_sha=target.head_sha),
        counts=_verdict_counts(artifacts.outcome),
        coverage=artifacts.discovered.coverage,
        findings=[],
        verdict="BLOCK",
        failures=[message],
    )


def _gate_invariant_failure(artifacts: _PipelineArtifacts, exc: GateInvariantError) -> None:
    save_gate_verdict(artifacts.run.dir, _gate_failure_verdict(artifacts, str(exc)))
    _error_console.print(str(exc), markup=False)
    raise typer.Exit(EXIT_NOT_FOUND) from exc


@app.command()
def gate(
    target: Annotated[str | None, Option("--target")] = None,
    run_id: Annotated[str | None, Option("--run")] = None,
    dispositions_path: Annotated[Path | None, Option("--dispositions")] = None,
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
    replicas: Annotated[int, Option("--replicas", min=1)] = _PLAN_REPLICAS,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
    execute: Annotated[bool, Option("--execute")] = False,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    """Run or resume a fail-closed, artifact-backed pull-request gate."""

    if (target is None) == (run_id is None):
        _error_console.print("gate requires exactly one of --target or --run", markup=False)
        raise typer.Exit(EXIT_USER_ERROR)
    asyncio.run(
        _gate_pipeline(
            target_spec=target,
            run_id=run_id,
            dispositions_path=dispositions_path,
            registry_root=registry_root,
            replicas=replicas,
            out_root=out_root,
            execute=execute,
            json_output=json_output,
        )
    )


async def _gate_pipeline(
    *,
    target_spec: str | None,
    run_id: str | None,
    dispositions_path: Path | None,
    registry_root: Path,
    replicas: int,
    out_root: Path,
    execute: bool,
    json_output: bool,
) -> None:
    artifacts: _PipelineArtifacts
    plan: GatePlan
    if target_spec is not None:
        try:
            resolved = _resolve_cli_target(target_spec)
        except (TargetResolutionError, ValueError) as exc:
            _error_console.print(str(exc), markup=False)
            raise typer.Exit(EXIT_USER_ERROR) from exc
        try:
            if resolved.kind != "pr" or resolved.pr_number is None or resolved.base_sha is None:
                _error_console.print("rvw gate requires a PR target", markup=False)
                raise typer.Exit(EXIT_USER_ERROR)
            plan = _gate_plan(registry_root, resolved, replicas)
            with tempfile.TemporaryDirectory(prefix="rvw-gate-") as temporary_root:
                checkout = provision_checkout(
                    repo=resolved.repo,
                    pr_number=resolved.pr_number,
                    head_sha=resolved.head_sha,
                    destination=Path(temporary_root) / "checkout",
                )
                executed = await _execute_pipeline(
                    target_spec=target_spec,
                    repo_dir=checkout,
                    registry_root=registry_root,
                    replicas=replicas,
                    out_root=out_root,
                    pause=False,
                    dynamic_brief=None,
                    resolved_target=resolved,
                )
            if executed is None:
                raise RuntimeError("gate review stopped before report generation")
            artifacts = executed
            save_gate_plan(artifacts.run.dir, plan)
        except typer.Exit:
            raise
        except EmptyReviewDiffError as exc:
            _empty_review_failure(exc, json_output=json_output)
        except GateInvariantError as exc:
            _error_console.print(str(exc), markup=False)
            raise typer.Exit(EXIT_NOT_FOUND) from exc
        except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
            _error_console.print(str(exc), markup=False)
            raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    else:
        assert run_id is not None
        try:
            artifacts = _load_gate_artifacts(run_id, out_root)
            plan = load_gate_plan(artifacts.run.dir)
        except (RunNotFound, StageMissing, OSError, ValueError) as exc:
            _error_console.print(str(exc), markup=False)
            raise typer.Exit(EXIT_NOT_FOUND) from exc

    target = artifacts.target
    if target.kind != "pr" or target.pr_number is None or target.base_sha is None:
        _error_console.print("rvw gate requires persisted PR artifacts", markup=False)
        raise typer.Exit(EXIT_USER_ERROR)
    anchor = GateAnchor(base_sha=target.base_sha, head_sha=target.head_sha)
    try:
        current = query_pull_request(target.repo, target.pr_number)
        verify_pull_request(anchor, current)
        coverage = validate_coverage(
            plan.lane_ids,
            artifacts.discovered.coverage,
            replicas=plan.replicas,
            chunk_count=plan.chunk_count,
        )
    except GateInvariantError as exc:
        _gate_invariant_failure(artifacts, exc)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc

    if artifacts.outcome is None:
        _gate_invariant_failure(artifacts, GateInvariantError("adjudication outcome is required"))
    outcome = cast(AdjudicationOutcome, artifacts.outcome)

    if dispositions_path is None:
        template_path = write_disposition_template(artifacts.run.dir, artifacts.merged, outcome)
        if any(
            verdict in {Verdict.CONFIRMED, Verdict.UNCERTAIN}
            for verdict in outcome.verdicts.values()
        ):
            save_gate_verdict(
                artifacts.run.dir,
                _gate_failure_verdict(
                    artifacts, "actionable findings require explicit dispositions"
                ),
            )
            _console.print(
                "actionable findings require dispositions — edit "
                f"{template_path} then resume: rvw gate --run {artifacts.run.run_id} "
                f"--dispositions {template_path}",
                markup=False,
                soft_wrap=True,
            )
            raise typer.Exit(EXIT_NOT_FOUND)
        dispositions = DispositionDocument(schema_version=1, dispositions=[])
    else:
        try:
            dispositions = load_dispositions(dispositions_path)
        except (OSError, ValueError) as exc:
            _error_console.print(str(exc), markup=False)
            raise typer.Exit(EXIT_USER_ERROR) from exc

    actor: str | None = None
    permission: str | None = None
    try:
        if requires_owner_authorization(artifacts.merged, outcome, dispositions):
            actor, permission = github_actor_permission(target.repo)
        verdict = build_gate_verdict(
            run_id=artifacts.run.run_id,
            target=target,
            coverage=coverage,
            merged=artifacts.merged,
            outcome=outcome,
            dispositions=dispositions,
            actor=actor,
            actor_permission=permission,
        )
    except GateInvariantError as exc:
        _gate_invariant_failure(artifacts, exc)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc

    verdict_path, markdown_path = save_gate_verdict(artifacts.run.dir, verdict)
    verdict_markdown = markdown_path.read_text(encoding="utf-8")
    try:
        publication = publish_review(
            run=artifacts.run,
            repo=target.repo,
            pr_number=target.pr_number,
            report_md=verdict_markdown,
            merged=artifacts.merged,
            outcome=outcome,
            execute=execute,
        )
    except (OSError, subprocess.CalledProcessError, PublishError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    payload = {
        "run_id": artifacts.run.run_id,
        "verdict": verdict.verdict,
        "verdict_path": str(verdict_path),
        "publish_payload_path": str(artifacts.run.dir / "publish-payload.json"),
        "review_url": publication.review_url,
    }
    if json_output:
        _write_json(payload)
    else:
        _console.print(f"run id: {artifacts.run.run_id}", markup=False)
        _console.print(f"verdict: {verdict.verdict}", markup=False)
        _console.print(f"gate artifact: {verdict_path}", markup=False, soft_wrap=True)
        if not execute:
            _console.print(
                f"dry-run payload: {artifacts.run.dir / 'publish-payload.json'}",
                markup=False,
                soft_wrap=True,
            )
        elif publication.review_url is not None:
            _console.print(f"review: {publication.review_url}", markup=False, soft_wrap=True)
    if verdict.verdict == "BLOCK":
        raise typer.Exit(EXIT_NOT_FOUND)


@app.command()
def auto(
    target: Annotated[str, Option("--target")],
    repo_dir: Annotated[
        Path | None,
        Option("--repo-dir", help="Provisioned checkout used for adjudication."),
    ] = None,
    policy_path: Annotated[Path, Option("--policy")] = DEFAULT_AUTO_POLICY,
    publish: Annotated[bool | None, Option("--publish/--no-publish")] = None,
    allow_approve: Annotated[bool, Option("--allow-approve")] = False,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    if allow_approve:
        _error_console.print(
            "approve publishing is not implemented (ADR-009 Phase-5 opt-in placeholder)",
            markup=False,
        )
    try:
        asyncio.run(
            _auto_pipeline(
                target_spec=target,
                repo_dir=repo_dir,
                policy_path=policy_path,
                publish=publish,
                json_output=json_output,
            )
        )
    except EmptyReviewDiffError as exc:
        _empty_review_failure(exc, json_output=json_output)


async def _auto_pipeline(
    *,
    target_spec: str,
    repo_dir: Path | None,
    policy_path: Path,
    publish: bool | None,
    json_output: bool,
) -> None:
    policy = load_policy(policy_path)
    artifacts = await _execute_pipeline(
        target_spec=target_spec,
        repo_dir=repo_dir,
        registry_root=DEFAULT_REGISTRY_ROOT,
        replicas=_PLAN_REPLICAS,
        out_root=DEFAULT_RUN_ROOT,
        pause=False,
        dynamic_brief=None,
    )
    if artifacts is None:
        raise RuntimeError("auto pipeline stopped before report generation")

    decision = evaluate(policy, artifacts.merged, artifacts.outcome)
    should_publish = policy.publish_state == "comment" if publish is None else publish
    if should_publish and artifacts.target.kind == "pr" and artifacts.target.pr_number is not None:
        publish_review(
            run=artifacts.run,
            repo=artifacts.target.repo,
            pr_number=artifacts.target.pr_number,
            report_md=artifacts.report_md,
            merged=artifacts.merged,
            outcome=artifacts.outcome,
            execute=True,
        )

    payload = {
        "run_id": artifacts.run.run_id,
        "verdict": decision.verdict,
        "blocking": decision.blocking,
        "dropped": decision.dropped,
        "promoted": decision.promoted,
        "considered": decision.considered,
        "report_path": str(artifacts.report_path),
    }
    if json_output:
        _write_json(payload)
    else:
        _console.print(f"run id: {artifacts.run.run_id}", markup=False, soft_wrap=True)
        _console.print(f"verdict: {decision.verdict}", markup=False)
        _console.print(f"report: {artifacts.report_path}", markup=False, soft_wrap=True)
    if decision.verdict == "BLOCK":
        raise typer.Exit(EXIT_NOT_FOUND)


@app.command()
def plan(
    target: Annotated[str, Option("--target")],
    json_output: Annotated[bool, Option("--json")] = False,
    pause: Annotated[bool, Option("--pause")] = False,
    dynamic_brief: Annotated[Path | None, Option("--dynamic-brief")] = None,
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
) -> None:
    del pause
    registry, lanes_root = _load_registry_root(registry_root)
    resolved_target = _resolve_cli_target(target)
    payload = _plan_payload(registry, lanes_root, resolved_target, dynamic_brief)
    if json_output:
        _write_json(payload)
    else:
        _print_plan(payload)


@app.command()
def run(run_id: Annotated[str | None, Option("--run")] = None) -> None:
    _stub(1)


@app.command("adjudicate")
def adjudicate_command(run_id: Annotated[str | None, Option("--run")] = None) -> None:
    _stub(3)


@app.command("report")
def report_command(
    run_id: Annotated[str, Option("--run")],
    synthesis: Annotated[Path | None, Option("--synthesis")] = None,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
) -> None:
    try:
        run = RunStore(out_root).open(run_id)
        target = run.load_target()
        discovered = run.load_discover()
        merged = run.load_merge()
        outcome = _optional_outcome(run)
    except (RunNotFound, StageMissing) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_NOT_FOUND) from exc

    synthesis_text = synthesis.read_text(encoding="utf-8") if synthesis is not None else None
    report_md = render_report(
        target=target,
        merged=merged,
        outcome=outcome,
        coverage=discovered.coverage,
        budget=discovered.budget,
        synthesis=synthesis_text,
    )
    run.save_report(report_md)
    _console.print(str(run.dir / "report.md"), markup=False, soft_wrap=True)


@app.command("publish")
def publish_command(
    run_id: Annotated[str, Option("--run")],
    execute: Annotated[bool, Option("--execute")] = False,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
) -> None:
    try:
        run = RunStore(out_root).open(run_id)
        target = run.load_target()
    except RunNotFound as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    except StageMissing as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_NOT_FOUND) from exc

    if target.kind != "pr" or target.pr_number is None:
        _error_console.print("rvw publish requires a PR target", markup=False)
        raise typer.Exit(EXIT_USER_ERROR)

    try:
        merged = run.load_merge()
        outcome = _optional_outcome(run)
        report_md = run.load_report()
    except StageMissing as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_NOT_FOUND) from exc
    result = publish_review(
        run=run,
        repo=target.repo,
        pr_number=target.pr_number,
        report_md=report_md,
        merged=merged,
        outcome=outcome,
        execute=execute,
    )
    if execute:
        _console.print(str(result.review_url), markup=False, soft_wrap=True)
    else:
        _console.print(str(run.dir / "publish-payload.json"), markup=False, soft_wrap=True)


@stack_app.command("plan")
def stack_plan(
    prs: Annotated[str, Option("--prs", help="Ordered comma-separated pull-request numbers.")],
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    """Resolve, validate, and persist an immutable explicit stack manifest."""

    try:
        numbers = parse_pr_numbers(prs)
        members = resolve_stack(numbers, cwd=Path.cwd())
        handle = StackStore(out_root).create(numbers)
        manifest = StackManifest(
            run_id=handle.run_id,
            repo=members[0].repo,
            members=members,
        )
        handle.save_manifest(manifest)
    except StackResolutionError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    except (StackInvariantError, ValueError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_USER_ERROR) from exc
    except OSError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc

    payload = {
        "run_id": handle.run_id,
        "manifest_path": str(handle.dir / "stack-manifest.json"),
        "repo": manifest.repo,
        "prs": [member.number for member in manifest.members],
    }
    if json_output:
        _write_json(payload)
    else:
        _console.print(f"stack run id: {handle.run_id}", markup=False)
        _console.print(
            f"manifest: {handle.dir / 'stack-manifest.json'}",
            markup=False,
            soft_wrap=True,
        )


@stack_app.command("review")
def stack_review(
    prs: Annotated[str, Option("--prs", help="Ordered comma-separated pull-request numbers.")],
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
    replicas: Annotated[int, Option("--replicas", min=1)] = 1,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    """Review every member and recheck earlier claims at descendant heads."""

    try:
        asyncio.run(
            _stack_review_pipeline(
                prs=prs,
                registry_root=registry_root,
                replicas=replicas,
                out_root=out_root,
                json_output=json_output,
            )
        )
    except EmptyReviewDiffError as exc:
        _empty_review_failure(exc, json_output=json_output)
    except StackResolutionError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    except (StackInvariantError, ValueError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_USER_ERROR) from exc
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc


async def _stack_review_pipeline(
    *,
    prs: str,
    registry_root: Path,
    replicas: int,
    out_root: Path,
    json_output: bool,
) -> None:
    numbers = parse_pr_numbers(prs)
    members = resolve_stack(numbers, cwd=Path.cwd())
    handle = StackStore(out_root).create(numbers)
    manifest = StackManifest(
        run_id=handle.run_id,
        repo=members[0].repo,
        members=members,
    )
    handle.save_manifest(manifest)
    member_runs: list[MemberRunRef] = []
    lineages: list[FindingLineage] = []
    coerced_evidence = 0
    handle.save_member_runs(member_runs)
    handle.save_lineages(lineages)

    for member in manifest.members:
        with tempfile.TemporaryDirectory(prefix=f"rvw-stack-pr-{member.number}-") as temp_root:
            checkout = provision_checkout(
                repo=member.repo,
                pr_number=member.number,
                head_sha=member.head_sha,
                destination=Path(temp_root) / "checkout",
            )
            target = resolved_target_for_member(member, cwd=checkout)
            artifacts = await _execute_pipeline(
                target_spec=str(member.number),
                repo_dir=checkout,
                registry_root=registry_root,
                replicas=replicas,
                out_root=out_root,
                pause=False,
                dynamic_brief=None,
                resolved_target=target,
            )
            if artifacts is None or artifacts.outcome is None:
                raise RuntimeError(
                    f"stack member PR #{member.number} stopped before adjudicated report"
                )
            member_runs.append(
                MemberRunRef(
                    pr_number=member.number,
                    run_id=artifacts.run.run_id,
                    report_path=str(artifacts.report_path),
                    verdict_counts=_verdict_counts(artifacts.outcome),
                )
            )
            handle.save_member_runs(member_runs)

            if lineages:
                presence = await adjudicate_presence(
                    lineages,
                    pr_number=member.number,
                    target=target,
                    runtime=CodexRuntime(),
                    repo_dir=checkout,
                    out_root=handle.dir / "presence-runtime" / f"pr-{member.number}",
                    replicas=replicas,
                )
                lineages = [
                    append_observation(
                        lineage,
                        presence.observations[lineage.lineage_id],
                    )
                    for lineage in lineages
                ]
                coerced_evidence += presence.coerced_evidence

            lineages.extend(
                origin_lineages(
                    pr_number=member.number,
                    run_id=artifacts.run.run_id,
                    merged=artifacts.merged,
                    outcome=artifacts.outcome,
                )
            )
            handle.save_lineages(
                lineages,
                coerced_evidence=coerced_evidence,
            )

    current = resolve_stack(numbers, cwd=Path.cwd(), repo=manifest.repo)
    verify_manifest(manifest, current)
    report_md = render_stack_report(manifest, member_runs, lineages)
    handle.save_report(report_md)
    handle.require_complete()

    payload = {
        "run_id": handle.run_id,
        "report_path": str(handle.dir / "stack-report.md"),
        "repo": manifest.repo,
        "prs": numbers,
        "member_runs": [member.run_id for member in member_runs],
        "lineages": len(lineages),
        "coerced_evidence": coerced_evidence,
    }
    if json_output:
        _write_json(payload)
    else:
        _console.print(f"stack run id: {handle.run_id}", markup=False)
        _console.print(
            f"stack report: {handle.dir / 'stack-report.md'}",
            markup=False,
            soft_wrap=True,
        )


@stack_app.command("publish")
def stack_publish(
    run_id: Annotated[str, Option("--run")],
    execute: Annotated[bool, Option("--execute")] = False,
    out_root: Annotated[Path, Option("--out")] = DEFAULT_RUN_ROOT,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    """Write or execute one body-only COMMENT review against the stack tip."""

    try:
        handle = StackStore(out_root).open(run_id)
        handle.require_complete()
        manifest = handle.load_manifest()
        report_md = handle.load_report()
        if execute:
            numbers = [member.number for member in manifest.members]
            current = resolve_stack(
                numbers,
                cwd=Path.cwd(),
                repo=manifest.repo,
            )
            verify_manifest(manifest, current)
        tip = manifest.members[-1]
        result = publish_body_review(
            run_dir=handle.dir,
            repo=manifest.repo,
            pr_number=tip.number,
            body=report_md,
            execute=execute,
        )
    except (StackRunNotFound, StackStageMissing) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_NOT_FOUND) from exc
    except StackResolutionError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc
    except StackInvariantError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_NOT_FOUND) from exc
    except (OSError, subprocess.CalledProcessError, PublishError, ValueError) as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_SYSTEM_ERROR) from exc

    payload = {
        "run_id": handle.run_id,
        "tip_pr": tip.number,
        "publish_payload_path": str(handle.dir / "publish-payload.json"),
        "review_url": result.review_url,
    }
    if json_output:
        _write_json(payload)
    elif execute:
        _console.print(str(result.review_url), markup=False, soft_wrap=True)
    else:
        _console.print(
            str(handle.dir / "publish-payload.json"),
            markup=False,
            soft_wrap=True,
        )


@lanes_app.command("list")
def lanes_list(
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
) -> None:
    registry, lanes_root = _load_registry_root(registry_root)
    table = Table(title="Registered review lanes")
    table.add_column("Lane")
    table.add_column("Tier")
    table.add_column("Cost")
    table.add_column("Rules", justify="right")
    table.add_column("Validation")
    for lane_id, tier_value in _registered_lane_owners(registry):
        lane = load_lane(resolve_lane_path(lanes_root, lane_id, tier_value))
        table.add_row(
            lane.id,
            lane.tier.value,
            lane.cost,
            str(len(lane.rules)),
            lane.validation or "validated",
        )
    _console.print(table)


@lanes_app.command("show")
def lanes_show(
    lane_id: Annotated[str, Argument(help="Lane ID to display.")],
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
) -> None:
    registry, lanes_root = _load_registry_root(registry_root)
    owner = next(
        (
            (registered_id, tier)
            for registered_id, tier in _registered_lane_owners(registry)
            if registered_id == lane_id
        ),
        None,
    )
    if owner is None:
        _error_console.print(f"unknown lane: {lane_id}")
        raise typer.Exit(EXIT_NOT_FOUND)
    path = resolve_lane_path(lanes_root, owner[0], owner[1])
    _console.print(f"Path: {path}", soft_wrap=True)
    _console.print(path.read_text(encoding="utf-8"), markup=False, highlight=False, soft_wrap=True)


def _print_doctor(report: DoctorReport) -> None:
    _console.print(f"Runs scanned: {report.runs_scanned}", markup=False)
    table = Table(title="Lane health")
    table.add_column("Lane")
    table.add_column("Runs", justify="right")
    table.add_column("Invalid", justify="right")
    table.add_column("Findings", justify="right")
    table.add_column("Other rate", justify="right")
    table.add_column("Flags")
    for stat in report.lanes:
        flags = []
        if stat.invalid > 0:
            flags.append("invalid")
        if stat.other_rate > 0.2:
            flags.append("other>20%")
        table.add_row(
            stat.lane_id,
            str(stat.runs),
            str(stat.invalid),
            str(stat.findings),
            f"{stat.other_rate:.1%}",
            ", ".join(flags) or "—",
        )
    _console.print(table)
    if report.adjudication is None:
        _console.print("Adjudication: no outcome stages found", markup=False)
        return
    stat = report.adjudication
    _console.print(
        "Adjudication:\n"
        f"  groups: {stat.groups}\n"
        f"  confirmed: {stat.confirmed}\n"
        f"  rejected: {stat.rejected}\n"
        f"  uncertain/unresolved: {stat.uncertain_unresolved}\n"
        f"  rejection rate: {stat.rejection_rate:.1%}\n"
        f"  coerced rejections: {stat.coerced_rejections}",
        markup=False,
    )


@app.command()
def doctor(
    store_root: Annotated[Path, Option("--store")] = DEFAULT_RUN_ROOT,
    last: Annotated[int, Option("--last", min=1)] = 20,
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    report = diagnose(RunStore(store_root), last=last)
    if json_output:
        _write_json(report.model_dump(mode="json"))
    else:
        _print_doctor(report)


def _fixture_diff(fixture: Path) -> str:
    try:
        content = fixture.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        content = None
    if content is not None and content.startswith(("diff --git ", "--- ")):
        return content

    try:
        completed = subprocess.run(
            ["git", "diff", "--no-index", "--", "/dev/null", str(fixture)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError(f"could not build fixture diff: {exc}") from exc
    if completed.returncode not in {0, 1}:
        detail = completed.stderr.strip() or f"git exited {completed.returncode}"
        raise ValueError(f"could not build fixture diff: {detail}")
    return completed.stdout


def _print_sample(report: SampleReport) -> None:
    table = Table(title=f"Lane sample: {report.lane_id}")
    table.add_column("Variant")
    table.add_column("Rule ID")
    table.add_column("Line", justify="right")
    table.add_column("Delta")
    enum_only = set(report.enum_only)
    free_only = set(report.free_only)
    for rule_id, line in report.enum_findings:
        table.add_row(
            "enum",
            rule_id,
            str(line) if line is not None else "—",
            "enum-only" if (rule_id, line) in enum_only else "",
        )
    for rule_id, line in report.free_findings:
        table.add_row(
            "free",
            rule_id,
            str(line) if line is not None else "—",
            "free-only" if (rule_id, line) in free_only else "",
        )
    _console.print(table)
    if report.novel_rule_ids:
        _console.print(f"Novel rule IDs: {', '.join(report.novel_rule_ids)}", markup=False)
    if report.site_variance:
        variance_table = Table(title="Replica site variance (non-gap)")
        variance_table.add_column("Variant")
        variance_table.add_column("Rule ID")
        variance_table.add_column("File")
        variance_table.add_column("Line", justify="right")
        for item in report.site_variance:
            variance_table.add_row(
                item.variant,
                item.rule_id,
                item.file,
                str(item.line) if item.line is not None else "—",
            )
        _console.print(variance_table)
        _console.print(f"site variance: {len(report.site_variance)}", markup=False)
    _console.print(f"Verdict: {report.verdict}", markup=False)


@app.command()
def sample(
    lane_id: Annotated[str, Option("--lane")],
    fixture: Annotated[Path, Option("--fixture")],
    registry_root: Annotated[
        Path, Option("--registry", help="Registry root containing layers.yaml and lanes/.")
    ] = DEFAULT_REGISTRY_ROOT,
    replicas: Annotated[int, Option("--replicas", min=1)] = 3,
    out_root: Annotated[Path, Option("--out")] = Path("/tmp/rvw-sample"),
    json_output: Annotated[bool, Option("--json")] = False,
) -> None:
    registry, lanes_root = _load_registry_root(registry_root)
    owner = next(
        (
            (registered_id, tier)
            for registered_id, tier in _registered_lane_owners(registry)
            if registered_id == lane_id
        ),
        None,
    )
    if owner is None:
        _error_console.print(f"unknown lane: {lane_id}", markup=False)
        raise typer.Exit(EXIT_NOT_FOUND)
    lane = load_lane(resolve_lane_path(lanes_root, owner[0], owner[1]))
    try:
        fixture_diff = _fixture_diff(fixture)
    except ValueError as exc:
        _error_console.print(str(exc), markup=False)
        raise typer.Exit(EXIT_USER_ERROR) from exc
    try:
        report = asyncio.run(
            sample_lane(
                lane,
                fixture_diff=fixture_diff,
                runtime=CodexRuntime(),
                out_root=out_root,
                replicas=replicas,
            )
        )
    except EmptyReviewDiffError as exc:
        _empty_review_failure(exc, json_output=json_output)
    if json_output:
        _write_json(asdict(report))
    else:
        _print_sample(report)
        if report.verdict == "PASS":
            _console.print(
                f"lane '{lane.id}' may drop 'validation: pending' — edit the lane doc to promote it.",
                markup=False,
            )
    if report.verdict == "REVIEW":
        raise typer.Exit(EXIT_NOT_FOUND)
