from pathlib import Path

from runner.models import RunState, Task
from runner.prompting import execution_prompt, should_refresh_goal


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


def test_full_goal_only_for_new_session_in_initial_cycle():
    run = state()
    assert should_refresh_goal(run, False)
    assert not should_refresh_goal(run, True)
    run.current = 1
    assert not should_refresh_goal(run, True)
    run.current = 3
    assert not should_refresh_goal(run, True)


def test_retry_does_not_repeat_full_goal_in_existing_session():
    run = state()
    run.tasks[0].attempts = 2
    assert not should_refresh_goal(run, True)


def test_first_repair_task_refreshes_goal():
    run = state(cycle=2)
    assert should_refresh_goal(run, True)


def test_execution_prompt_never_embeds_full_goal():
    run = state()
    fresh = execution_prompt(run, Path("/tmp"), [], include_goal=True)
    continued = execution_prompt(run, Path("/tmp"), [], include_goal=False)
    assert "ORIGINAL GOAL" not in fresh
    assert "ORIGINAL GOAL" not in continued
    assert "Treat the current TODO as self-contained" in fresh
    assert "Do not read the original goal or planning output" in fresh
    assert "current TODO is the only executable scope" in continued


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
