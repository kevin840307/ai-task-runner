from argparse import Namespace
from pathlib import Path

import pytest

from runner.api import RunRequest
from runner.models import Task


def test_review_policy_defaults_and_cli_namespace():
    request = RunRequest(goal='g', project_root='.', validator='ai')
    request.validate()
    args = request.to_namespace()
    assert args.review_error_retries == 3
    assert args.strict_review is False


def test_review_retries_must_be_positive():
    request = RunRequest(goal='g', project_root='.', validator='ai', review_error_retries=0)
    with pytest.raises(ValueError, match='positive integer'):
        request.validate()


def test_task_review_audit_fields_round_trip():
    task = Task(id='c01-t001', title='t', description='d')
    assert task.review_skipped is False
    assert task.review_error_attempts == 0
    assert task.review_session_rebuilds == 0


def test_from_namespace_accepts_legacy_cli_namespace_without_review_fields():
    from argparse import Namespace

    from runner.defaults import DEFAULT_REVIEW_ERROR_RETRIES

    values = {
        "goal": "g",
        "goal_file": None,
        "project_root": ".",
        "script": None,
        "validator": "ai",
        "validator_prompt": "",
        "backend": "qwen",
        "command": None,
        "agent_arg": [],
        "validator_arg": [],
        "protect_file": [],
        "validator_timeout": 300,
        "agent_timeout": 0,
        "planning_timeout": 0,
        "agent_idle_after_change_timeout": 0,
        "max_attempts": 0,
        "max_cycles": 0,
        "retry_delay": 0,
        "retry_wait": 0,
        "retry_max_wait": 0,
        "work_dir": ".ai-task-runner",
        "resume": False,
        "force_new": False,
        "plan_only": False,
        "json_events": False,
    }

    request = RunRequest.from_namespace(Namespace(**values))

    assert request.review_error_retries == DEFAULT_REVIEW_ERROR_RETRIES
    assert request.strict_review is False


def test_task_changed_files_round_trip():
    from runner.models import RunState

    state = RunState(
        run_id="r",
        goal="g",
        project_root=".",
        tasks=[Task(
            id="c01-t001",
            title="t",
            description="d",
            changed_files=["a.py", "b.yaml"],
        )],
    )

    loaded = RunState.load(state.dump())
    assert loaded.tasks[0].changed_files == ["a.py", "b.yaml"]


def test_review_rebuilds_fresh_session_and_counts_each_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import runner.core as core
    from runner.errors import RunnerError
    from runner.models import RunState

    created_sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            created_sessions.append(kwargs["session_id"])

    calls = 0

    def fake_readonly_ask(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RunnerError("temporary review failure")
        return ('{"completed":true,"reason":"ok","missing_items":[]}', [], [])

    class UI:
        def start(self, *args): pass
        def stop(self, *args): pass
        def set(self, *args): pass

    task = Task(
        id="c01-t001",
        title="t",
        description="d",
        deliverable="x",
        acceptance_criteria=["x exists"],
        changed_files=["x.txt"],
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_arg=[],
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
        review_error_retries=3,
        strict_review=False,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.ui = UI()
    runner._save_state = lambda: None

    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence", True)

    assert result["completed"] is True
    assert created_sessions == ["", ""]
    assert task.review_error_attempts == 1
    assert task.review_session_rebuilds == 1


def test_review_tolerant_mode_stops_after_configured_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import runner.core as core
    from runner.errors import RunnerError
    from runner.models import RunState

    created_sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            created_sessions.append(kwargs["session_id"])

    def fake_readonly_ask(*args, **kwargs):
        raise RunnerError("review unavailable")

    class UI:
        def start(self, *args): pass
        def stop(self, *args): pass
        def set(self, *args): pass

    task = Task(
        id="c01-t001",
        title="t",
        description="d",
        deliverable="x",
        acceptance_criteria=["x exists"],
        changed_files=["x.txt"],
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_arg=[],
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
        review_error_retries=3,
        strict_review=False,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.ui = UI()
    runner._save_state = lambda: None

    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence", True)

    assert result["completed"] is True
    assert result["review_skipped"] is True
    assert created_sessions == ["", "", ""]
    assert task.review_error_attempts == 3
    assert task.review_session_rebuilds == 3


def test_review_budget_is_persisted_across_function_reentry(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import runner.core as core
    from runner.errors import RunnerError
    from runner.models import RunState

    created_sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            created_sessions.append(kwargs["session_id"])

    def fake_readonly_ask(*args, **kwargs):
        raise RunnerError("review unavailable")

    class UI:
        def start(self, *args): pass
        def stop(self, *args): pass
        def set(self, *args): pass

    task = Task(
        id="c01-t001",
        title="t",
        description="d",
        review_error_attempts=2,
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_arg=[],
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
        review_error_retries=3,
        strict_review=False,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.ui = UI()
    runner._save_state = lambda: None

    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence", False)

    assert result["review_skipped"] is True
    assert task.review_error_attempts == 3
    assert created_sessions == [""]


def test_review_budget_already_exhausted_skips_without_new_call(tmp_path):
    from types import SimpleNamespace

    import runner.core as core
    from runner.models import RunState

    task = Task(
        id="c01-t001",
        title="t",
        description="d",
        review_error_attempts=3,
        review_skip_reason="saved error",
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(review_error_retries=3, strict_review=False)
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )

    result = core.TaskRunner._review_current_task(runner, task, "evidence", False)

    assert result == {
        "completed": True,
        "reason": "saved error",
        "missing_items": [],
        "review_skipped": True,
    }


def test_strict_review_budget_exhaustion_is_terminal(tmp_path):
    from types import SimpleNamespace

    import pytest

    import runner.core as core
    from runner.errors import ReviewUnavailableError
    from runner.models import RunState

    task = Task(
        id="c01-t001",
        title="t",
        description="d",
        review_error_attempts=3,
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(review_error_retries=3, strict_review=True)
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )

    with pytest.raises(ReviewUnavailableError, match="review failed 3 times"):
        core.TaskRunner._review_current_task(runner, task, "evidence", False)


def test_qwen_review_args_disable_mutating_tools():
    from runner.agent_args import review_agent_args

    args = review_agent_args("qwen", [])

    for tool in ("write_file", "edit", "notebook_edit", "run_shell_command"):
        index = args.index(tool)
        assert args[index - 1] == "--exclude-tools"
