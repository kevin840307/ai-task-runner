from __future__ import annotations

import json
from types import SimpleNamespace

from runner.plugins.console import ConsoleObserver, LiveUI
from runner.runtime.run_state import RunState, Task


def _state(tmp_path):
    return RunState(
        "run-1",
        "goal",
        str(tmp_path),
        cycle=2,
        current=1,
        tasks=[
            Task("t1", "First TODO", "first", status="completed", attempts=1),
            Task("t2", "Second TODO", "second", attempts=2),
            Task("t3", "Third TODO", "third"),
        ],
    )


def test_live_ui_snapshot_uses_same_cli_task_markers(tmp_path):
    ui = LiveUI(human_output=False)
    state = _state(tmp_path)
    ui.bind(state)
    ui.set("AI running skill", "Second TODO")

    snap = ui.snapshot()

    assert snap is not None
    assert snap["cycle"] == 2
    assert snap["completed_count"] == 1
    assert [item["mark"] for item in snap["tasks"]] == ["x", ">", " "]
    assert snap["lines"][:5] == [
        "AI Task Runner  Cycle 2  Progress 1/3",
        "",
        "  [x] 1. First TODO",
        "  [>] 2. Second TODO",
        "  [ ] 3. Third TODO",
    ]
    assert snap["lines"][-2:] == ["  {spinner} AI running skill", "    Second TODO"]


def test_console_observer_persists_cli_view_for_ui_without_importing_core(tmp_path):
    runtime = SimpleNamespace(config=SimpleNamespace(human_output=False), work=tmp_path)
    observer = ConsoleObserver(runtime)
    state = _state(tmp_path)

    observer({"type": "runner.progress", "action": "bind", "state": state})
    observer({"type": "runner.status", "action": "start", "status": "Review running", "detail": "Second TODO"})

    path = tmp_path / "console-view.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "Review running"
    assert payload["detail"] == "Second TODO"
    assert payload["tasks"][1]["mark"] == ">"
    assert payload["lines"][-2] == "  {spinner} Review running"


def test_console_observer_persists_yaml_script_child_pointer(tmp_path):
    runtime = SimpleNamespace(config=SimpleNamespace(human_output=False), work=tmp_path)
    observer = ConsoleObserver(runtime)
    child_root = tmp_path / "child"

    observer({
        "type": "script.item_started",
        "script_index": 2,
        "script_total": 4,
        "prompt_preview": "second task",
        "child_project_root": str(child_root),
        "child_work_dir": ".ai-task-runner/script/002",
    })

    payload = json.loads((tmp_path / "console-view.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "script"
    assert payload["script_index"] == 2
    assert payload["script_total"] == 4
    assert payload["script_status"] == "running"
    assert payload["child_project_root"] == str(child_root)
    assert payload["child_work_dir"] == ".ai-task-runner/script/002"
    assert payload["prompt_preview"] == "second task"
