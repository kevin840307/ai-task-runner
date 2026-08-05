from pathlib import Path
from types import SimpleNamespace

from runner.core import EXECUTION_FAILURES_BEFORE_REVIEW
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


def test_execution_prompt_does_not_embed_full_goal_or_completed_task_list(tmp_path):
    prompt = execution_prompt(state(), tmp_path, [], include_goal=True)
    assert "Build the entire application including many later features." not in prompt
    assert '"completed_tasks"' not in prompt
    assert "current TODO is the only executable scope" in prompt
    assert "Do not run the final project validator" in prompt


def test_execution_failure_review_threshold_is_small_and_positive():
    assert EXECUTION_FAILURES_BEFORE_REVIEW == 2


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
    assert "Do not read the original goal or planning output" in prompt
    assert "current TODO is the only executable work item" in prompt


def test_execution_error_uses_cumulative_task_changes_for_review(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import runner.core as core
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001",
        title="Current task",
        description="Do current work",
        deliverable="result",
        acceptance_criteria=["result exists"],
        stagnant_attempts=1,
        changed_files=["saved-from-attempt-1.txt"],
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.agent = SimpleNamespace(session_id="")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner.args = SimpleNamespace()
    runner._save_state = lambda: None
    runner._save_session = lambda: None
    runner._set_stage = lambda *args: None
    runner._review_current_task = lambda *args: {
        "completed": True,
        "reason": "saved work satisfies the task",
        "missing_items": [],
    }
    runner._handle_review_result = lambda *args: 77

    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])

    result = core.TaskRunner._handle_execution_error(
        runner,
        task,
        RunnerError("attempt 2 failed without a new file"),
        {},
    )

    assert result == 77
    assert task.changed_files == ["saved-from-attempt-1.txt"]
