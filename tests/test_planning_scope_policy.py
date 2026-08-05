from pathlib import Path

from runner.models import RunState, Task
from runner.prompting import plan_prompt, plan_refine_prompt


def test_planner_requires_self_contained_bounded_tasks(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    prompt = plan_prompt("g", tmp_path, state, [])

    assert "Every TODO must be self-contained for execution" in prompt
    assert "without rereading the original goal or planning output" in prompt
    assert "acceptance criteria must provide enough evidence to know when to stop" in prompt
    assert "constraints in every task's acceptance criteria" in prompt


def test_plan_refine_preserves_self_contained_task_contract(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    tasks = [Task(
        id="c01-t001",
        title="One result",
        description="Create one result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )]
    prompt = plan_refine_prompt("g", tmp_path, state, tasks)

    assert "Every TODO must be self-contained for execution" in prompt
    assert "exact end result" in prompt
    assert "smaller model can complete one coherent step" in prompt
