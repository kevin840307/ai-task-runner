from pathlib import Path
from types import SimpleNamespace

from runner.core import EXECUTION_NO_CHANGE_FAILURES_BEFORE_DEFER
from runner.models import RunState, Task
from runner.prompting import execution_prompt


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
    assert "scratch, diagnostic, runner-state, or sidecar files" in prompt
    assert "Make the smallest maintainable change that satisfies the deliverable and acceptance criteria" in prompt
    assert "If no project change is required, do not modify files" in prompt


def test_no_change_failure_defer_threshold_is_small_and_positive():
    assert EXECUTION_NO_CHANGE_FAILURES_BEFORE_DEFER == 2


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


def test_execution_error_with_current_changes_reviews_immediately(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    runner._review_current_task = lambda *args: {
        "completed": True, "reason": "saved work satisfies the task", "missing_items": []
    }
    runner._handle_review_result = lambda *args: 77
    monkeypatch.setattr(core, "changed_project_files", lambda *args: ["result.txt"])

    result = core.TaskRunner._handle_execution_error(runner, task, RunnerError("failed"), {})

    assert result == 77
    assert task.changed_files == ["result.txt"]
    assert runner.agent.session_id == ""


def test_old_changes_do_not_count_as_progress_for_current_failed_attempt(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
        changed_files=["saved-from-previous-attempt.txt"],
    )
    runner = _runner(tmp_path, task)
    runner._review_current_task = lambda *args: (_ for _ in ()).throw(AssertionError("must not review"))
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])

    result = core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {})

    assert result is None
    assert task.status == "pending"
    assert task.stagnant_attempts == 1
    assert runner.agent.session_id == ""


def test_two_same_fresh_no_change_failures_defer_to_validator(tmp_path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    completed = []
    runner._complete_current_task = lambda value: completed.append(value.id)
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])

    assert core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {}) is None
    runner.agent.session_id = "fresh-session"
    assert core.TaskRunner._handle_execution_error(runner, task, RunnerError("same failure"), {}) is None

    assert completed == [task.id]
    assert task.review_skipped is True
    assert "final validator" in task.review_skip_reason.lower()
    assert runner.agent.session_id == ""
