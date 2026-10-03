from __future__ import annotations

from runner.errors import RunnerError
from runner.runtime.run_state import RunState, Task
from runner.workflow import dynamic_expansion as expansion
from runner.workflow.stages import PlanStage, StageResult


def _state(tmp_path):
    return RunState("run", "goal", str(tmp_path))


def _task(task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        title="Task",
        description="Do work",
        deliverable="artifact",
        acceptance_criteria=["artifact exists"],
    )


def test_plan_stage_owns_task_to_child_stage_shape():
    children = PlanStage._plan_child_stages([_task("a"), _task("b")])

    assert [(item["profile"], item.get("task_id")) for item in children] == [
        ("execute", "a"),
        ("review", "a"),
        ("execute", "b"),
        ("review", "b"),
    ]
    assert children[1]["routes"] == {"fail": "task_001_execute"}
    assert children[1]["task_complete"] is True
    assert children[3]["routes"] == {"fail": "task_002_execute"}
    assert children[3]["task_complete"] is True


def test_runner_does_not_infer_child_stages_from_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(expansion.progress, "show_todo", lambda _state: None)
    state = _state(tmp_path)
    result = StageResult(
        "producer",
        "pass",
        data={"tasks": [_task()]},
        kind="tasks",
    )

    try:
        expansion.expand_stage_result(
            state=state,
            workflow=[{"name": "producer", "type": "command", "produces": "tasks"}],
            source_index=0,
            source={"name": "producer", "type": "command", "produces": "tasks"},
            result=result,
            continuation="next",
        )
    except RunnerError as error:
        assert "must provide a non-empty stages array" in str(error)
    else:
        raise AssertionError("Runner unexpectedly inferred child Stage structure")


def test_producer_defined_children_are_inserted_before_parent_continuation(tmp_path, monkeypatch):
    monkeypatch.setattr(expansion.progress, "show_todo", lambda _state: None)
    state = _state(tmp_path)
    workflow = [
        {"name": "a", "type": "command", "command": ["echo", "a"]},
        {"name": "producer", "type": "command", "command": ["echo", "p"], "produces": "tasks"},
        {"name": "d", "type": "command", "command": ["echo", "d"]},
    ]
    result = StageResult(
        "producer",
        "pass",
        kind="tasks",
        data={
            "tasks": [_task("work")],
            "stages": [
                {"name": "execute", "type": "base", "profile": "execute", "task_id": "work"},
                {
                    "name": "review",
                    "type": "base",
                    "profile": "review",
                    "task_id": "work",
                    "task_complete": True,
                    "routes": {"fail": "execute"},
                },
            ],
        },
    )

    expanded = expansion.expand_stage_result(
        state=state,
        workflow=workflow,
        source_index=1,
        source=workflow[1],
        result=result,
        continuation="next",
    )

    assert expanded is not None
    assert [item["name"] for item in expanded] == [
        "a",
        "producer",
        "producer__g1__execute",
        "producer__g1__review",
        "d",
    ]
    assert expanded[3]["routes"]["fail"] == "producer__g1__execute"
    assert expanded[3]["_dynamic_continue"] == "next"
    assert state.expanded_workflow == expanded
    assert state.dynamic_groups == {"producer": "producer__g1"}
    assert state.dynamic_task_groups == {"producer": ["producer__g1__work"]}


def test_rerunning_same_producer_replaces_old_children_and_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(expansion.progress, "show_todo", lambda _state: None)
    state = _state(tmp_path)
    source = {"name": "producer", "type": "command", "command": ["echo", "p"], "produces": "tasks"}
    parent = [source, {"name": "after", "type": "command", "command": ["echo", "d"]}]

    def result(task_id: str) -> StageResult:
        return StageResult(
            "producer",
            "pass",
            kind="tasks",
            data={
                "tasks": [_task(task_id)],
                "stages": [{
                    "name": "child",
                    "type": "base",
                    "profile": "generic",
                    "task_id": task_id,
                    "task_complete": True,
                }],
            },
        )

    first = expansion.expand_stage_result(
        state=state, workflow=parent, source_index=0, source=source,
        result=result("one"), continuation="next",
    )
    assert first is not None
    old_child = "producer__g1__child"
    state.stage_sessions[old_child] = "session-old"
    state.review_failures[f"{old_child}::__run__"] = 2
    second = expansion.expand_stage_result(
        state=state, workflow=first, source_index=0, source=source,
        result=result("two"), continuation="next",
    )

    assert second is not None
    names = [item["name"] for item in second]
    assert "producer__g1__child" not in names
    assert "producer__g2__child" in names
    assert [task.id for task in state.tasks] == ["producer__g2__two"]
    assert state.dynamic_groups == {"producer": "producer__g2"}
    assert old_child not in state.stage_sessions
    assert not any(key.startswith(f"{old_child}::") for key in state.review_failures)
