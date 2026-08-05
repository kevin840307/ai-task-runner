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
