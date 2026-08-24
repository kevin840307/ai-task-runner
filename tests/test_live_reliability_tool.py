from __future__ import annotations

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
