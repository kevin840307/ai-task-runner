from types import SimpleNamespace

import pytest

from runner.errors import ConfigurationError
from runner.runtime.run_state import RunState, Task
from runner.workflow_runner import WorkflowRunner


def _runner(tmp_path, workflow):
    runner = WorkflowRunner.__new__(WorkflowRunner)
    runner.root = tmp_path
    runner.config = SimpleNamespace(
        resume=True,
        force_new=False,
        work_dir=".work",
        workflow=workflow,
    )
    runner.state = RunState("run", "goal", str(tmp_path))
    return runner


def test_resume_requires_frozen_workflow_snapshot(tmp_path):
    runner = _runner(tmp_path, [{"name": "work", "type": "base"}])

    with pytest.raises(ConfigurationError, match="snapshot not found"):
        runner._bind_workflow_snapshot()


def test_resume_rejects_workflow_position_outside_saved_workflow(tmp_path):
    runner = _runner(tmp_path, [{"name": "work", "type": "base"}])
    runner.state.workflow_position = 2

    with pytest.raises(ConfigurationError, match="workflow_position"):
        runner._validate_resume_state()


def test_resume_rejects_session_for_stage_not_in_saved_workflow(tmp_path):
    runner = _runner(tmp_path, [{"name": "work", "type": "base"}])
    runner.state.stage_sessions = {"removed_stage": "session-1"}

    with pytest.raises(ConfigurationError, match="unknown Stages"):
        runner._validate_resume_state()


def test_resume_rejects_dynamic_stage_bound_to_unknown_task(tmp_path):
    runner = _runner(tmp_path, [{"name": "parent", "type": "base"}])
    runner.state.expanded_workflow = [
        {"name": "parent", "type": "base"},
        {
            "name": "parent__g1__execute",
            "type": "base",
            "_dynamic_task_id": "missing-task",
        },
    ]

    with pytest.raises(ConfigurationError, match="unknown task"):
        runner._validate_resume_state()


def test_resume_accepts_consistent_dynamic_state(tmp_path):
    runner = _runner(tmp_path, [{"name": "parent", "type": "base"}])
    runner.state.tasks = [Task("task-1", "Task", "Do it")]
    runner.state.expanded_workflow = [
        {"name": "parent", "type": "base"},
        {
            "name": "parent__g1__execute",
            "type": "base",
            "_dynamic_task_id": "task-1",
        },
    ]
    runner.state.stage_sessions = {"parent__g1__execute": "session-1"}

    runner._validate_resume_state()
