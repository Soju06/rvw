from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from rvw.pipeline import execute_pipeline
from rvw.target import ResolvedTarget


def target() -> ResolvedTarget:
    return ResolvedTarget(
        kind="commit",
        repo="owner/repo",
        base_sha="0" * 40,
        head_sha="1" * 40,
        changed_paths=["a.py"],
        diff="diff --git a/a.py b/a.py\n",
    )


def test_execute_pipeline_exposes_only_split_replica_parameters() -> None:
    parameters = inspect.signature(execute_pipeline).parameters

    assert "replicas" not in parameters
    assert "discover_replicas" in parameters
    assert "adjudicate_replicas" in parameters


@pytest.mark.parametrize(
    ("discover_replicas", "adjudicate_replicas", "message"),
    [
        (0, 3, "discover_replicas must be at least 1"),
        (1, 0, "adjudicate_replicas must be at least 1"),
    ],
)
async def test_execute_pipeline_validates_both_replica_counts_before_creating_a_run(
    tmp_path: Path,
    discover_replicas: int,
    adjudicate_replicas: int,
    message: str,
) -> None:
    unused: Any = None

    with pytest.raises(ValueError, match=message):
        await execute_pipeline(
            registry=unused,
            lanes_root=tmp_path,
            target=target(),
            active_lanes=[],
            runtime=unused,
            adjudicator=unused,
            repo_dir=None,
            discover_replicas=discover_replicas,
            adjudicate_replicas=adjudicate_replicas,
            concurrency=8,
            out_root=tmp_path / "runs",
            pause=False,
            dynamic_brief=None,
        )

    assert not (tmp_path / "runs").exists()
