from types import SimpleNamespace

from runner.agent.prompts import execution_prompt, render_prompt_template
from runner.models import RunState, Task


def state(attempts=1):
    return RunState(
        run_id="r",
        goal="Build the entire application including many later features.",
        project_root=".",
        tasks=[Task(
            id="c01-t001",
            title="Inspect current structure",
            description="Inspect only",
            deliverable="A factual structure summary",
            acceptance_criteria=["No unrelated implementation"],
            attempts=attempts,
        )],
    )


def test_fresh_execution_prompt_embeds_goal_as_context_not_completed_task_list(tmp_path):
    prompt = execution_prompt(state(), tmp_path, [], include_goal=True)
    assert "Build the entire application including many later features." in prompt
    assert '"completed_tasks"' not in prompt
    assert "Current TODO is the only executable scope" in prompt
    assert "Do not run the final project validator" in prompt
    assert "satisfied or safely improved" in prompt
    assert "ad hoc verification files" in prompt
    assert "remove any temporary artifacts before finishing" in prompt
    assert "Make the smallest maintainable change that satisfies the deliverable and acceptance criteria" in prompt
    assert "If no project change is required, do not modify files" in prompt


def test_execution_prompt_keeps_only_shared_global_constraints(tmp_path):
    shared = "Preserve public interfaces and avoid hardcoding"
    current = state()
    current.tasks[0].acceptance_criteria.append(shared)
    current.tasks.append(Task(
        id="c01-t002",
        title="Later feature",
        description="Do later work",
        deliverable="Later result",
        acceptance_criteria=["Later result exists", shared],
    ))

    prompt = execution_prompt(current, tmp_path, [], include_goal=True)

    assert shared in prompt
    assert "Later feature" not in prompt
    assert "never use it to discover or perform later work" in prompt
    assert "Current TODO is the only executable scope" in prompt


def _runner(tmp_path, task):
    import runner.core as core

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task])
    runner.agent = SimpleNamespace(session_id="old-session")
    runner.ui = SimpleNamespace(set=lambda *args: None, bind=lambda *args: None)
    runner.args = SimpleNamespace(max_attempts=0, retry_delay=0)
    runner._save_state = lambda: None
    runner._save_session = lambda: None
    runner._set_stage = lambda *args: None
    return runner


def test_task_completion_emits_one_state_transition(tmp_path, monkeypatch):
    import runner.core as core

    task = Task(
        id="c01-t001",
        title="Focused change",
        description="Do work",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    events = []
    runner.ui = SimpleNamespace(
        set=lambda *args: events.append(args),
        bind=lambda *args: None,
    )
    monkeypatch.setattr(
        core,
        "show_todo",
        lambda *args: events.append(("duplicate progress",)),
    )

    core.TaskRunner._complete_current_task(runner, task)

    assert task.status == "completed"
    assert runner.state.current == 1
    assert events == [("任務完成", "Focused change")]


def test_execution_error_with_current_changes_reviews_immediately(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    events = []
    runner.ui = SimpleNamespace(set=lambda *args: events.append(args))
    runner._review_current_task = lambda *args: {
        "completed": True, "reason": "saved work satisfies the task", "missing_items": []
    }
    runner._handle_review_result = lambda *args: 77
    monkeypatch.setattr(core, "changed_project_files", lambda *args: ["result.txt"])

    result = core.TaskRunner._handle_execution_error(runner, task, RunnerError("failed"), {})

    assert result == 77
    assert task.changed_files == ["result.txt"]
    assert runner.agent.session_id == "old-session"
    assert "task_recovery_action=review_changed_work" in events[0][1]


def test_old_changes_do_not_count_as_progress_for_current_failed_attempt(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
        changed_files=["saved-from-previous-attempt.txt"],
    )
    runner = _runner(tmp_path, task)
    events = []
    runner.ui = SimpleNamespace(
        set=lambda *args: events.append(args),
        bind=lambda *args: None,
    )
    runner._review_current_task = lambda *args: (_ for _ in ()).throw(AssertionError("must not review"))
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])

    result = core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {})

    assert result is None
    assert task.status == "pending"
    assert task.stagnant_attempts == 1
    assert runner.agent.session_id == "old-session"
    assert "task_recovery_action=retry_task" in events[0][1]


def test_three_same_no_change_failures_rebuild_session_but_keep_todo_pending(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])

    assert core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {}) is None
    assert core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {}) is None
    assert runner.agent.session_id == "old-session"
    assert core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {}) is None

    assert task.status == "pending"
    assert task.review_skipped is False
    assert runner.agent.session_id == ""
    assert task.stagnant_attempts == 0


def test_completed_todo_preserves_executor_session_for_next_todo(tmp_path, monkeypatch):
    import runner.core as core

    tasks = [
        Task(id="c01-t001", title="one", description="d", deliverable="a", acceptance_criteria=["a"]),
        Task(id="c01-t002", title="two", description="d", deliverable="b", acceptance_criteria=["b"]),
    ]
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(max_attempts=0, retry_delay=0)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=tasks)
    runner.agent = SimpleNamespace(session_id="executor-session")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._save_state = lambda: None
    runner._set_stage = lambda *args: None
    seen = []
    runner._execute_current_task = lambda task: seen.append((task.id, runner.agent.session_id)) or "done"
    runner._review_current_task = lambda *args: {"completed": True, "reason": "ok", "missing_items": []}
    monkeypatch.setattr(core, "project_manifest", lambda *args: {})
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])
    monkeypatch.setattr(core, "show_todo", lambda *args: None)

    assert runner._run_pending_tasks() is None
    assert seen == [("c01-t001", "executor-session"), ("c01-t002", "executor-session")]
    assert runner.agent.session_id == "executor-session"
    assert runner.state.agent_session_id == "executor-session"


def test_normal_executor_completion_without_file_change_still_reviews(tmp_path, monkeypatch):
    import runner.core as core

    task = Task(id="c01-t001", title="check existing result", description="d", deliverable="d", acceptance_criteria=["ok"])
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(max_attempts=0, retry_delay=0)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task])
    runner.agent = SimpleNamespace(session_id="s")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._save_state = lambda: None
    runner._save_session = lambda: None
    runner._set_stage = lambda *args: None
    runner._execute_current_task = lambda task: "already satisfied"
    seen = []
    runner._review_current_task = lambda task, output: seen.append((task.id, output)) or {"completed": True, "reason": "ok", "missing_items": []}
    monkeypatch.setattr(core, "project_manifest", lambda *args: {})
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])
    monkeypatch.setattr(core, "show_todo", lambda *args: None)

    assert runner._run_pending_tasks() is None
    assert seen == [("c01-t001", "already satisfied")]
    assert task.status == "completed"


def test_validator_repair_hint_is_scoped_to_current_todo():
    prompt = render_prompt_template("validator_repair_hint.md", {"repeat_hint": ""})
    lower = prompt.lower()
    assert "first reported validator failure" not in lower
    assert "current todo" in lower
    assert "relevant" in lower
    assert "ignore unrelated validator failures" in lower
    assert "later-todo" in lower


def test_execution_prompt_stops_after_focused_success(tmp_path):
    prompt = execution_prompt(state(), tmp_path, [], include_goal=True)
    assert "smallest focused verification" in prompt
    assert "if it passes, stop immediately" in prompt.lower()
    assert "Do not repeat the same inspection or test hypothesis without new evidence" in prompt
