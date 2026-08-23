from pathlib import Path

from runner.engine.models import RunState, Task
from runner.agent.prompts import execution_prompt, should_refresh_goal


def state(cycle=1):
    return RunState(
        run_id="r", goal="ORIGINAL GOAL", project_root="/tmp", cycle=cycle,
        tasks=[
            Task(
                id=f"c{cycle:02d}-t{i + 1:03d}", title="task", description="do it",
                deliverable="result", acceptance_criteria=["done"], attempts=1,
            )
            for i in range(6)
        ],
    )


def test_full_goal_only_for_new_session():
    assert should_refresh_goal(False)
    assert not should_refresh_goal(True)


def test_fresh_execution_includes_goal_and_next_todo_resume_is_task_only():
    run = state()
    fresh = execution_prompt(run, Path("/tmp"), [], include_goal=True)
    run.current = 1
    next_todo = execution_prompt(run, Path("/tmp"), [], include_goal=False)
    assert "ORIGINAL GOAL" in fresh
    assert "ORIGINAL GOAL" not in next_todo
    assert "context and global constraints only; never executable scope" in fresh
    assert "Current TODO is the only executable scope" in fresh
    assert "Continue in the existing work session" in next_todo
    assert "Work only on this Current TODO" in next_todo
    assert '"title": "task"' in next_todo
    assert "Do not redo completed work" in next_todo


def test_rebuilt_session_prompt_requires_read_before_modify():
    run = state()
    run.tasks[0].attempts = 2
    prompt = execution_prompt(
        run,
        Path("/tmp"),
        [],
        include_goal=True,
        rebuilt_session=True,
    )
    assert "continuing in a rebuilt session" in prompt
    assert "read its current full content" in prompt
    assert "never immediately repeat the identical tool call" in prompt


def test_normal_session_omits_rebuilt_notice():
    run = state()
    prompt = execution_prompt(run, Path("/tmp"), [], rebuilt_session=False)
    assert "continuing in a rebuilt session" not in prompt


def test_rebuilt_session_includes_original_goal_and_current_task():
    run = state()
    run.tasks[0].attempts = 3
    prompt = execution_prompt(
        run,
        Path("/tmp"),
        [],
        include_goal=True,
        rebuilt_session=True,
    )
    assert "ORIGINAL GOAL" in prompt
    assert '"title": "task"' in prompt
    assert "Rebuilt session notice" in prompt
    assert "Current TODO is the only executable scope" in prompt


def test_same_session_retry_is_short_and_carries_only_new_feedback():
    run = state()
    run.tasks[0].attempts = 2
    run.tasks[0].last_review = {
        "completed": False,
        "reason": "Missing rendered file",
        "missing_items": ["Create output.yaml"],
    }
    run.tasks[0].last_output = "Previous execution summary"
    prompt = execution_prompt(
        run,
        Path("/tmp"),
        [],
        strategy_note="Fix the first blocking issue",
        include_goal=False,
    )
    assert "Continue only the same current TODO" in prompt
    assert "Missing rendered file" in prompt
    assert "Create output.yaml" in prompt
    assert "Previous execution summary" not in prompt
    assert "Fix the first blocking issue" in prompt
    assert "ORIGINAL GOAL" not in prompt
    assert '"description": "do it"' not in prompt
    assert "Project root:" not in prompt
