from pathlib import Path

from runner.models import RunState, Task
from runner.prompting import review_finalize_prompt, review_prompt


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


def test_review_prompt_is_changed_files_first_and_does_not_embed_full_goal(tmp_path: Path):
    shared = "Preserve existing behavior and avoid hardcoding"
    state = RunState(
        run_id="r",
        goal="Build every feature in the full application",
        project_root=str(tmp_path),
        tasks=[
            Task(
                id="c01-t001",
                title="Implement one bounded result",
                description="Change only the current result.",
                deliverable="Current result",
                acceptance_criteria=["Current result works", shared],
                changed_files=["src/current.py"],
            ),
            Task(
                id="c01-t002",
                title="Implement later result",
                description="A later task.",
                deliverable="Later result",
                acceptance_criteria=["Later result works", shared],
            ),
        ],
    )

    prompt = review_prompt(state, tmp_path, [], "focused check passed")

    assert "Build every feature in the full application" not in prompt
    assert "Inspect the files changed during this TODO first" in prompt
    assert 'src/current.py' in prompt
    assert shared in prompt
    assert "Do not broadly explore the repository" in prompt
    assert "Do not run the full project validator" in prompt


def test_review_finalize_prompt_forces_decision_without_more_exploration():
    prompt = review_finalize_prompt()
    assert "Finalize the current review now" in prompt
    assert "do not use any more tools" in prompt
    assert "Do not redo implementation" in prompt
    assert '"completed":true' in prompt
    assert '"completed":false' in prompt
