from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from ui.task_service import TaskService

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "13_concurrent_worktree_conflict" / "live_qwen_demo.py"
BAT = ROOT / "examples" / "13_concurrent_worktree_conflict" / "run_live_qwen_conflict_test.bat"
RALPHY = ROOT / "runner" / "assets" / "workflows" / "ralphy_ai_validate.yaml"


def _load_live_demo():
    spec = importlib.util.spec_from_file_location("live_qwen_conflict_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def test_live_qwen_conflict_demo_reuses_existing_ralphy_workflow(tmp_path: Path) -> None:
    module = _load_live_demo()

    assert module.RALPHY_WORKFLOW.resolve() == RALPHY.resolve()
    assert module.RALPHY_WORKFLOW.is_file()

    project = module._init_project(tmp_path)
    assert _git(project, "ls-files").splitlines() == ["shared.txt"]
    assert not (project / "live_qwen_workflow.yaml").exists()
    assert not (project / "live_qwen_prompt.md").exists()

    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    task = module._create_task(tasks, project, "TASK_A")
    item = task["items"][0]
    assert Path(item["workflow"]).resolve() == RALPHY.resolve()
    assert item["workspace"] == "main"

    command = module._runner_command(
        project,
        module._task_goal("TASK_A"),
        qwen_command="qwen.cmd",
        timeout=123,
    )
    assert command[command.index("--backend") + 1] == "qwen"
    assert command[command.index("--command") + 1] == "qwen.cmd"
    assert Path(command[command.index("--workflow") + 1]).resolve() == RALPHY.resolve()
    assert command[command.index("--agent-timeout") + 1] == "123"


def test_live_qwen_conflict_bat_calls_real_qwen_not_mock_agent() -> None:
    text = BAT.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "qwen.cmd" in lowered
    assert "live_qwen_demo.py" in lowered
    assert "ralphy_ai_validate.yaml" in lowered
    assert "mock_agent.py" not in lowered
    assert "conflict_recovery_agent.py" not in lowered
    assert "live_qwen_workflow.yaml" not in lowered
