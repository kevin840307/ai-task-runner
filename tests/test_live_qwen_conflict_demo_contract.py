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


def test_live_qwen_clean_check_ignores_only_runner_runtime_state(tmp_path: Path) -> None:
    module = _load_live_demo()
    project = module._init_project(tmp_path)

    runtime = project / ".ai-task-runner" / "ui"
    runtime.mkdir(parents=True)
    (runtime / "tasks.json").write_text('{"tasks": []}\n', encoding="utf-8")

    # This is intentionally the same exception used by production MergeManager:
    # runner-owned lifecycle metadata is allowed to be untracked.
    assert module._source_status_ignoring_runner_runtime(project) == ""

    unexpected = project / "unexpected.txt"
    unexpected.write_text("real source change\n", encoding="utf-8")
    status = module._source_status_ignoring_runner_runtime(project)

    assert "unexpected.txt" in status
    assert ".ai-task-runner" not in status

def test_live_qwen_conflict_demo_cleans_task_and_recovery_workspaces() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert source.count("service.cleanup(") >= 2
    assert '"worktree", "list", "--porcelain"' in source
    assert '"local/task/"' in source
    assert '"local/recovery/"' in source
    assert '"cleanup_result_count": len(cleanup_rows)' in source
    assert '"remaining_worktrees": len(worktree_paths)' in source

