from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from runner.errors import RunnerError
from runner.runtime.run_state import RunState, Task
from runner.workflow.dynamic_expansion import expand_stage_result
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.loader import load_workflow
from runner.workflow.stages import StageResult
from tool.workflow_dryrun import (
    DryRunContext,
    DryRunLimit,
    MockStageExecutor,
    Scenario,
    _close,
    _execute,
)


def _names(executor: MockStageExecutor) -> list[str]:
    return [stage for _number, stage, _label, _status in executor.trace]


def test_plan_expands_multiple_execute_review_pairs_before_parent_continues() -> None:
    workflow = [
        {"name": "planning", "type": "plan"},
        {"name": "after", "type": "base", "profile": "generic"},
    ]
    ctx, executor, error = _execute(workflow, Scenario(), 30)
    try:
        assert error == ""
        assert ctx.state.completed is True
        assert _names(executor) == [
            "planning",
            "planning__g1__task_001_execute",
            "planning__g1__task_001_review",
            "planning__g1__task_002_execute",
            "planning__g1__task_002_review",
            "after",
        ]
        assert [task.status for task in ctx.state.tasks] == ["completed", "completed"]
        assert ctx.state.expanded_workflow
    finally:
        _close(ctx)


def test_plan_review_fail_loops_only_its_own_execute_then_continues() -> None:
    workflow = [
        {"name": "planning", "type": "plan"},
        {"name": "after", "type": "base", "profile": "generic"},
    ]
    scenario = Scenario({
        "stages": {
            "planning__g1__task_001_review": ["fail", "pass"],
        }
    })
    ctx, executor, error = _execute(workflow, scenario, 40)
    try:
        assert error == ""
        names = _names(executor)
        assert names == [
            "planning",
            "planning__g1__task_001_execute",
            "planning__g1__task_001_review",
            "planning__g1__task_001_execute",
            "planning__g1__task_001_review",
            "planning__g1__task_002_execute",
            "planning__g1__task_002_review",
            "after",
        ]
        assert ctx.state.completed is True
    finally:
        _close(ctx)


def test_generic_stage_can_produce_child_stages_without_runner_inference() -> None:
    workflow = [
        {"name": "generator", "type": "base", "produces": "stages"},
        {"name": "after", "type": "base", "profile": "generic"},
    ]
    ctx, executor, error = _execute(workflow, Scenario(), 20)
    try:
        assert error == ""
        assert _names(executor) == [
            "generator",
            "generator__g1__dryrun_child",
            "after",
        ]
        assert ctx.state.completed is True
    finally:
        _close(ctx)


def test_nested_task_producers_keep_independent_task_groups() -> None:
    state = RunState(run_id="run", goal="goal", project_root="/tmp/project")
    parent_task = Task(
        id="t1",
        title="parent",
        description="parent task",
        deliverable="parent output",
        acceptance_criteria=["done"],
    )
    workflow = [
        {"name": "parent", "type": "base", "produces": "tasks"},
        {"name": "after", "type": "base"},
    ]
    parent_result = StageResult(
        "parent",
        "pass",
        data={
            "tasks": [parent_task],
            "stages": [
                {
                    "name": "nested",
                    "type": "base",
                    "produces": "tasks",
                    "task_id": "t1",
                },
                {
                    "name": "parent_done",
                    "type": "base",
                    "profile": "review",
                    "task_id": "t1",
                    "task_complete": True,
                },
            ],
        },
        kind="tasks",
    )
    expanded = expand_stage_result(
        state=state,
        workflow=workflow,
        source_index=0,
        source=workflow[0],
        result=parent_result,
        continuation="next",
    )
    assert expanded is not None
    parent_id = state.dynamic_task_groups["parent"][0]

    nested_index = next(
        index for index, item in enumerate(expanded)
        if item["name"].endswith("__nested")
    )
    nested = expanded[nested_index]
    nested_task = Task(
        id="t1",
        title="nested",
        description="nested task",
        deliverable="nested output",
        acceptance_criteria=["done"],
    )
    nested_result = StageResult(
        nested["name"],
        "pass",
        data={
            "tasks": [nested_task],
            "stages": [
                {
                    "name": "nested_execute",
                    "type": "base",
                    "profile": "execute",
                    "task_id": "t1",
                },
                {
                    "name": "nested_review",
                    "type": "base",
                    "profile": "review",
                    "task_id": "t1",
                    "task_complete": True,
                },
            ],
        },
        kind="tasks",
    )
    nested_expanded = expand_stage_result(
        state=state,
        workflow=expanded,
        source_index=nested_index,
        source=nested,
        result=nested_result,
        continuation="next",
    )
    assert nested_expanded is not None
    nested_id = state.dynamic_task_groups[nested["name"]][0]
    assert parent_id != nested_id
    assert {task.id for task in state.tasks} == {parent_id, nested_id}


def test_resume_uses_durable_expanded_workflow_without_rerunning_producer(tmp_path: Path) -> None:
    workflow = [
        {"name": "planning", "type": "plan"},
        {"name": "after", "type": "base", "profile": "generic"},
    ]
    ctx = DryRunContext(tmp_path, workflow)
    first = MockStageExecutor(Scenario(), max_steps=1)
    with pytest.raises(DryRunLimit):
        FlowEngine(ctx).run(first)

    assert _names(first) == ["planning"]
    assert ctx.state.workflow_position == 1
    assert ctx.state.expanded_workflow

    saved = RunState.load(ctx.state.dump())
    ctx.state = saved
    second = MockStageExecutor(Scenario(), max_steps=30)
    assert FlowEngine(ctx).run(second) == 0
    assert second.trace
    assert _names(second)[0].endswith("__task_001_execute")
    assert "planning" not in _names(second)
    assert ctx.state.completed is True


@pytest.mark.parametrize(
    "stage",
    [
        {"type": "base", "scope": "task"},
        {"type": "task"},
        {"type": "review"},
    ],
)
def test_removed_task_scope_contract_is_rejected(tmp_path: Path, stage: dict) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        yaml.safe_dump({
            "stages": {"legacy": stage},
            "flow": ["legacy"],
        }),
        encoding="utf-8",
    )
    with pytest.raises(RunnerError):
        load_workflow(path)


def test_removed_task_step_state_is_rejected() -> None:
    data = RunState(
        run_id="run",
        goal="goal",
        project_root="/tmp/project",
    ).dump()
    data["task_step"] = 0
    with pytest.raises(ValueError, match="removed fields"):
        RunState.load(data)


def test_dynamic_producer_explicit_parent_route_runs_children_before_target() -> None:
    workflow = [
        {
            "name": "generator",
            "type": "base",
            "produces": "stages",
            "routes": {"pass": "target"},
        },
        {"name": "skipped", "type": "base", "profile": "generic"},
        {"name": "target", "type": "base", "profile": "generic"},
    ]
    ctx, executor, error = _execute(workflow, Scenario(), 20)
    try:
        assert error == ""
        assert _names(executor) == [
            "generator",
            "generator__g1__dryrun_child",
            "target",
        ]
        assert ctx.state.completed is True
    finally:
        _close(ctx)


def test_dynamic_child_done_returns_to_parent_continuation() -> None:
    state = RunState(run_id="run", goal="goal", project_root="/tmp/project")
    workflow = [
        {"name": "generator", "type": "base", "produces": "stages"},
        {"name": "after", "type": "base", "profile": "generic"},
    ]
    result = StageResult(
        "generator",
        "pass",
        data={
            "stages": [
                {
                    "name": "child",
                    "type": "base",
                    "profile": "generic",
                    "routes": {"pass": "done"},
                }
            ]
        },
        kind="stages",
    )
    expanded = expand_stage_result(
        state=state,
        workflow=workflow,
        source_index=0,
        source=workflow[0],
        result=result,
        continuation="next",
    )
    assert expanded is not None
    child = expanded[1]
    assert child["_dynamic_group_continue"] == "next"
    assert child["_dynamic_continue"] == "next"



def test_dynamic_child_routes_cannot_escape_parent_workflow() -> None:
    state = RunState(run_id="run", goal="goal", project_root="/tmp/project")
    workflow = [
        {"name": "generator", "type": "base", "produces": "stages"},
        {"name": "after", "type": "base"},
    ]
    result = StageResult(
        "generator",
        "pass",
        data={
            "stages": [
                {
                    "name": "child",
                    "type": "base",
                    "routes": {"pass": "after"},
                }
            ]
        },
        kind="stages",
    )
    with pytest.raises(RunnerError, match="must stay inside the child Workflow"):
        expand_stage_result(
            state=state,
            workflow=workflow,
            source_index=0,
            source=workflow[0],
            result=result,
            continuation="next",
        )


def test_dynamic_child_handoff_targets_must_be_local() -> None:
    state = RunState(run_id="run", goal="goal", project_root="/tmp/project")
    workflow = [
        {"name": "generator", "type": "base", "produces": "stages"},
        {"name": "after", "type": "base"},
    ]
    result = StageResult(
        "generator",
        "pass",
        data={
            "stages": [
                {
                    "name": "router",
                    "type": "handoff",
                    "targets": ["after"],
                }
            ]
        },
        kind="stages",
    )
    with pytest.raises(RunnerError, match="handoff target must stay inside"):
        expand_stage_result(
            state=state,
            workflow=workflow,
            source_index=0,
            source=workflow[0],
            result=result,
            continuation="next",
        )


def test_task_reduction_does_not_install_tasks_before_dynamic_expansion(tmp_path: Path) -> None:
    from runner.config.runtime import RuntimeConfig
    from runner.workflow.results import reduce_result
    from runner.workflow.stages import StageContext

    state = RunState(run_id="run", goal="goal", project_root=str(tmp_path))
    task = Task(
        id="t1",
        title="one",
        description="one",
        deliverable="one",
        acceptance_criteria=["done"],
    )
    ctx = StageContext(
        config=RuntimeConfig(
            goal="goal",
            project_root=str(tmp_path),
            workflow=[{"name": "producer", "type": "base", "produces": "tasks"}],
            workflow_explicit=True,
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=type("AI", (), {"session_id": ""})(),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_args, **_kwargs: None,
    )
    result = reduce_result(
        ctx,
        StageResult(
            "producer",
            "pass",
            data={
                "tasks": [task],
                "stages": [
                    {
                        "name": "execute",
                        "type": "base",
                        "profile": "execute",
                        "task_id": "t1",
                    },
                    {
                        "name": "review",
                        "type": "base",
                        "profile": "review",
                        "task_id": "t1",
                        "task_complete": True,
                    },
                ],
            },
            kind="tasks",
        ),
    )
    assert result.kind == "tasks"
    assert state.tasks == []
