from pathlib import Path

from runner.engine.models import RunState, Task
from runner.agent.prompts import (
    ai_validator_prompt,
    execution_prompt,
    plan_finalize_prompt,
    plan_judge_prompt,
    plan_refine_prompt,
    plan_understand_prompt,
    review_finalize_prompt,
    review_prompt,
)


def _state(root: Path) -> RunState:
    return RunState(
        run_id="r",
        goal="g",
        project_root=str(root),
        tasks=[Task(
            id="c01-t001",
            title="Implement result",
            description="Create one result",
            deliverable="result",
            acceptance_criteria=["result exists"],
        )],
    )


def test_always_instructions_are_injected_into_every_ai_prompt_family(tmp_path: Path) -> None:
    marker = "USER_ALWAYS_RULE_9F31"
    (tmp_path / ".ai-task-runner.yaml").write_text(
        f"instructions:\n  always: {marker}\n",
        encoding="utf-8",
    )
    state = _state(tmp_path)
    task = state.tasks

    fresh_prompts = [
        plan_understand_prompt("g", tmp_path, state),
        plan_finalize_prompt("g", tmp_path, state, same_session=False),
        plan_refine_prompt("g", tmp_path, state, task, same_session=False),
        plan_judge_prompt("g", tmp_path, state, task, same_session=False),
        execution_prompt(state, tmp_path, [], include_goal=True),
        review_prompt(state, tmp_path, "done"),
        review_finalize_prompt(tmp_path),
        ai_validator_prompt("g", tmp_path, []),
    ]

    assert all(marker in prompt for prompt in fresh_prompts)
    assert marker not in plan_finalize_prompt("g", tmp_path, state, same_session=True)
    assert marker not in execution_prompt(state, tmp_path, [], include_goal=False)


def test_project_instructions_are_not_duplicated_into_direct_prompts(tmp_path: Path) -> None:
    marker = "PROJECT_ONLY_RULE_7C22"
    (tmp_path / ".ai-task-runner.yaml").write_text(
        f"instructions:\n  project: {marker}\n",
        encoding="utf-8",
    )
    state = _state(tmp_path)

    assert marker not in execution_prompt(state, tmp_path, [])
    assert marker not in plan_understand_prompt("g", tmp_path, state)
