"""Run the synthesis stage through real Codex validation with an offline spawn."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_synthesis import document, group, merged, outcome_for, target

import rvw.runtimes.codex as codex
from rvw.presentation import PresentationConfig
from rvw.runtime_policy import CodexRuntimePolicy
from rvw.synthesis import synthesize


@pytest.mark.parametrize("first_output", ["{", '{"overview":"missing fields"}'])
@pytest.mark.parametrize("mode", list(codex.CodexRuntimeMode))
async def test_real_runtime_retries_invalid_json_with_errors_and_retains_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first_output: str,
    mode: codex.CodexRuntimeMode,
) -> None:
    candidate = group()
    valid = document(candidate)
    calls: list[str] = []

    async def spawn(
        cmd: list[str],
        stdin_text: str,
        log_path: Path,
        *,
        cwd: Path | None = None,
    ) -> int:
        assert cwd is None
        assert cmd[cmd.index("--model") + 1] == "configured-model"
        assert "shell_tool" in cmd and "--ignore-rules" in cmd
        calls.append(stdin_text)
        Path(cmd[cmd.index("-o") + 1]).write_text(
            first_output if len(calls) == 1 else valid.model_dump_json(), encoding="utf-8"
        )
        log_path.write_text("codex\ncompleted\ntokens used\n42\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(codex, "_spawn", spawn)
    runtime = codex.CodexRuntime(
        policy=CodexRuntimePolicy(model="configured-model", reasoning_effort="medium"),
        mode=mode,
        no_output_seconds=19,
    )
    result, facts = await synthesize(
        target=target(),
        merged=merged(candidate),
        outcome=outcome_for([candidate]),
        coverage=[],
        status="complete",
        presentation=PresentationConfig(locale="ko"),
        runtime=runtime,
        out_root=tmp_path,
        deadline_seconds=37,
    )
    assert result == valid
    assert facts.status == "ok"
    assert (facts.model, facts.reasoning_effort, facts.tool_calls) == (
        "configured-model",
        "medium",
        0,
    )
    assert len(calls) == 2
    assert "Validation feedback" in calls[1]
    assert ("Field required" if first_output.startswith('{"') else "Expecting") in calls[1]
    for label in ("initial", "retry"):
        run_dir = tmp_path / label / "r1"
        usage = json.loads((run_dir / "usage.json").read_text())
        assert usage["no_output_seconds"] == 19
        assert usage["runtime_mode"] == "tool-less"
        assert usage["model"] == "configured-model"
        assert (run_dir / "schema.json").is_file()
        assert (run_dir / "prompt.md").is_file()
