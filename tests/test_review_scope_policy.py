from pathlib import Path

from runner.models import RunState, Task
from runner.prompting import review_prompt


def test_review_prompt_limits_decision_to_current_task(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="Build the whole project",
        project_root=str(tmp_path),
        tasks=[
            Task(
                id="c01-t001",
                title="Inspect current structure",
                description="Inspect only the current project structure.",
                deliverable="Inspection report",
                acceptance_criteria=["Existing structure is documented"],
            ),
            Task(
                id="c01-t002",
                title="Implement later feature",
                description="Implement a later feature.",
                deliverable="Feature implementation",
                acceptance_criteria=["Feature works"],
            ),
        ],
    )
    prompt = review_prompt(state, tmp_path, [], "created report")
    assert "current task is the only PASS/FAIL scope" in prompt
    assert "Do not require completion of later tasks" in prompt
    assert "Never include later-task or whole-project work" in prompt


def test_review_prompt_limits_validator_feedback_to_current_task(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="Build the whole project",
        project_root=str(tmp_path),
        validator_output="Later feature is still missing",
        tasks=[Task(
            id="c01-t001",
            title="Inspect current structure",
            description="Inspect only the current project structure.",
            deliverable="Inspection report",
            acceptance_criteria=["Existing structure is documented"],
        )],
    )
    prompt = review_prompt(state, tmp_path, [], "created report")
    assert "use only the parts relevant to the current task" in prompt
    assert "must not block this task" in prompt
