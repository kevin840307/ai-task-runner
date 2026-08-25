from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tool import qwen_live_reliability as live


def settings(tmp_path: Path) -> live.Settings:
    return live.Settings(
        workspace=tmp_path,
        command="qwen",
        sandbox=False,
        run_timeout=60,
        agent_timeout=30,
        planning_timeout=30,
        pause=0,
        api_port=8080,
        soak_final_ai_every=8,
        soak_transient_api_every=4,
        soak_timeout_every=6,
        soak_yaml_every=7,
        soak_sandbox_every=7,
    )


def test_script_command_uses_canonical_yaml_entry(tmp_path: Path):
    script = tmp_path / "tasks.yaml"
    command = live.runner_command(settings(tmp_path), tmp_path, script=script, resume=True)

    assert command[command.index("--script") + 1] == str(script)
    assert "--goal-file" not in command
    assert "--validator" not in command
    assert "--resume" in command


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_runner_command_inputs_select_builtin_validation_workflows(tmp_path: Path):
    project = tmp_path / "project"
    config = replace(settings(tmp_path), agent_timeout=30.0, planning_timeout=40.0)

    file_only = live.runner_command(config, project)
    assert _option(file_only, "--validator") == str(project / "validation.py")
    assert "--ai-validator-prompt" not in file_only
    assert "--validator-prompt" not in file_only
    assert "--workflow" not in file_only

    mixed = live.runner_command(config, project, final_ai=True)
    assert _option(mixed, "--validator") == str(project / "validation.py")
    assert _option(mixed, "--ai-validator-prompt") == live.FINAL_AI_PROMPT
    assert "--validator-prompt" not in mixed
    assert "--workflow" not in mixed

    ai_only = live.runner_command(config, project, final_ai=True, ai_only=True)
    assert _option(ai_only, "--validator") == "ai"
    assert _option(ai_only, "--validator-prompt") == live.FINAL_AI_PROMPT
    assert "--ai-validator-prompt" not in ai_only
    assert "--workflow" not in ai_only
    assert _option(file_only, "--agent-timeout") == "30"
    assert _option(file_only, "--planning-timeout") == "40"


def test_runner_timeout_arguments_must_be_whole_seconds():
    assert live.whole_seconds_arg(12.0) == "12"
    with pytest.raises(ValueError, match="whole seconds"):
        live.whole_seconds_arg(12.5)


def test_dense_coverage_requires_every_mixed_probe():
    complete = live.SoakResult(
        completed=1,
        mixed_validations=1,
        transient_recoveries=1,
        timeout_probes=1,
        yaml_runs=1,
        sandbox_runs=1,
        elapsed_seconds=1800,
    )
    live.require_dense_coverage(complete)

    with pytest.raises(RuntimeError, match="sandbox"):
        live.require_dense_coverage(
            live.SoakResult(
                completed=1,
                mixed_validations=1,
                transient_recoveries=1,
                timeout_probes=1,
                yaml_runs=1,
                elapsed_seconds=1800,
            )
        )


def test_assert_completed_supports_yaml_child_work_dir(tmp_path: Path):
    work = tmp_path / ".ai-task-runner" / "script" / "001"
    (work / "debug").mkdir(parents=True)
    (work / "state.json").write_text(
        '{"completed": true, "stage": "completed"}', encoding="utf-8"
    )
    (work / "log.txt").write_text("{}\n", encoding="utf-8")
    (work / "debug" / "last-prompt.txt").write_text("prompt", encoding="utf-8")
    (work / "debug" / "last-result.txt").write_text("result", encoding="utf-8")
    (tmp_path / "health.txt").write_text(live.EXPECTED, encoding="utf-8")

    live.assert_completed(tmp_path, 0, work_dir=".ai-task-runner/script/001")
