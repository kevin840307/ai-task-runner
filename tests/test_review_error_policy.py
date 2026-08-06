from types import SimpleNamespace

from runner.models import RunState, Task


def test_review_policy_options_are_removed_from_public_request():
    from runner.api import RunRequest

    request = RunRequest(goal="g", project_root=".", validator="ai")
    request.validate()
    args = request.to_namespace()

    assert not hasattr(args, "review_error_retries")
    assert not hasattr(args, "strict_review")


def test_legacy_review_counter_fields_are_ignored_when_loading_state():
    payload = RunState(
        run_id="r",
        goal="g",
        project_root=".",
        tasks=[Task(id="c01-t001", title="t", description="d")],
    ).dump()
    payload["tasks"][0]["review_error_attempts"] = 3
    payload["tasks"][0]["review_session_rebuilds"] = 3

    loaded = RunState.load(payload)

    assert loaded.tasks[0].title == "t"
    assert "review_error_attempts" not in loaded.dump()["tasks"][0]
    assert "review_session_rebuilds" not in loaded.dump()["tasks"][0]


def test_review_error_is_skipped_after_one_independent_call(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    created_sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            created_sessions.append(kwargs["session_id"])

    def fake_readonly_ask(*args, **kwargs):
        raise RunnerError("review unavailable")

    class UI:
        def start(self, *args):
            pass
        def stop(self, *args):
            pass
        def set(self, *args):
            pass

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

    result = core.TaskRunner._review_current_task(runner, task, "evidence")

    assert result["completed"] is True
    assert result["review_skipped"] is True
    assert created_sessions == [""]
    assert task.review_skip_reason.endswith("review unavailable")


def test_review_explicit_fail_is_not_skipped(tmp_path, monkeypatch):
    import runner.core as core

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

    def fake_readonly_ask(*args, **kwargs):
        return (
            '{"completed":false,"reason":"missing","missing_items":["x"]}',
            [],
            [],
        )

    class UI:
        def start(self, *args):
            pass
        def stop(self, *args):
            pass
        def set(self, *args):
            pass

    task = Task(id="c01-t001", title="t", description="d")
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_arg=[],
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.ui = UI()

    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence")

    assert result == {
        "completed": False,
        "reason": "missing",
        "missing_items": ["x"],
    }


def test_qwen_review_args_disable_mutating_tools():
    from runner.agent_args import review_agent_args

    args = review_agent_args("qwen", [])

    for tool in ("write_file", "edit", "notebook_edit", "run_shell_command"):
        index = args.index(tool)
        assert args[index - 1] == "--exclude-tools"
