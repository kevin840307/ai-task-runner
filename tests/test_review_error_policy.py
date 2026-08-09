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


def test_review_error_without_session_is_skipped_after_one_independent_call(tmp_path, monkeypatch):
    import runner.core as core
    import runner.reviewing as reviewing
    from runner.errors import RunnerError

    created_sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            created_sessions.append(self.session_id)

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

    monkeypatch.setattr(reviewing, "AgentClient", FakeAgent)
    monkeypatch.setattr(reviewing, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence")

    assert result["completed"] is True
    assert result["review_skipped"] is True
    assert created_sessions == [""]
    assert task.review_skip_reason.endswith("review unavailable")


def test_review_explicit_fail_is_not_skipped(tmp_path, monkeypatch):
    import runner.core as core
    import runner.reviewing as reviewing

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

    monkeypatch.setattr(reviewing, "AgentClient", FakeAgent)
    monkeypatch.setattr(reviewing, "readonly_ask", fake_readonly_ask)

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


def test_review_error_with_session_finalizes_without_tools(tmp_path, monkeypatch):
    import runner.core as core
    import runner.reviewing as reviewing
    from runner.errors import RunnerError

    agents = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            self.extra_args = kwargs["extra_args"]
            agents.append(self)

    calls = []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        calls.append((agent, prompt, kwargs.get("preserve_session_on_error", False)))
        if len(calls) == 1:
            agent.session_id = "review-session"
            raise RunnerError("review unavailable")
        return (
            '{"completed":true,"reason":"enough evidence","missing_items":[]}',
            [],
            [],
        )

    class UI:
        def start(self, *args): pass
        def stop(self, *args): pass
        def set(self, *args): pass

    task = Task(
        id="c01-t001", title="t", description="d", deliverable="x",
        acceptance_criteria=["x exists"], changed_files=["x.txt"],
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen", command=None, agent_arg=[], planning_timeout=1,
        agent_idle_after_change_timeout=0, retry_wait=0, retry_max_wait=0,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task])
    runner.ui = UI()
    runner._save_state = lambda: None

    monkeypatch.setattr(reviewing, "AgentClient", FakeAgent)
    monkeypatch.setattr(reviewing, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence")

    assert result == {"completed": True, "reason": "enough evidence", "missing_items": []}
    assert [agent.session_id for agent in agents] == ["review-session", "review-session"]
    assert calls[0][2] is True
    assert calls[1][2] is False
    assert "Finalize the current review now" in calls[1][1]
    excluded = {
        agents[1].extra_args[index + 1]
        for index, value in enumerate(agents[1].extra_args[:-1])
        if value == "--exclude-tools"
    }
    assert "read_file" not in excluded
    for tool in ("list_directory", "grep_search", "write_file", "run_shell_command"):
        assert tool in excluded


def test_review_finalize_error_still_skips_to_final_validator(tmp_path, monkeypatch):
    import runner.core as core
    import runner.reviewing as reviewing
    from runner.errors import RunnerError

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]

    calls = 0

    def fake_readonly_ask(agent, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            agent.session_id = "review-session"
            raise RunnerError("review loop")
        raise RunnerError("finalize failed")

    class UI:
        def start(self, *args): pass
        def stop(self, *args): pass
        def set(self, *args): pass

    task = Task(id="c01-t001", title="t", description="d")
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen", command=None, agent_arg=[], planning_timeout=1,
        agent_idle_after_change_timeout=0, retry_wait=0, retry_max_wait=0,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.protected = []
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task])
    runner.ui = UI()
    runner._save_state = lambda: None

    monkeypatch.setattr(reviewing, "AgentClient", FakeAgent)
    monkeypatch.setattr(reviewing, "readonly_ask", fake_readonly_ask)

    result = core.TaskRunner._review_current_task(runner, task, "evidence")

    assert calls == 2
    assert result["review_skipped"] is True
    assert result["completed"] is True
    assert task.review_skip_reason.endswith("finalize failed")
