from types import SimpleNamespace

import pytest

import runner.workflow.pipeline as pipeline_module
from runner.runtime.run_state import Task
from runner.workflow.pipeline import Pipeline
from runner.workflow.stages.contracts import StageResult


class Stage:
    mode = "readonly"
    actor = "test"
    status = "test"
    detail = ""
    retry = 0
    plan_only_stop = False

    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def stage_factory(monkeypatch):
    monkeypatch.setattr(
        pipeline_module, "create_stage", lambda item: Stage(item["name"])
    )


def item(name, **extra):
    return {"name": name, "type": "fake", **extra}


class Executor:
    def __init__(self, callback):
        self.callback = callback
        self.seen = []

    def run(self, stage, ctx, previous=None):
        self.seen.append(stage.name)
        return self.callback(stage, ctx, previous)


def context(workflow, tasks=None):
    state = SimpleNamespace(
        completed=False,
        workflow_position=0,
        current=0,
        tasks=list(tasks or []),
        dynamic_steps=[],
        dynamic_index=0,
        stage="created",
        validator_failure_key="",
        validator_failure_count=0,
        ai_session_id="",
        replan_feedback="",
    )
    return SimpleNamespace(
        state=state,
        config=SimpleNamespace(workflow=workflow, max_cycles=10),
        ai_client=SimpleNamespace(session_id=""),
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
        reset_sessions=lambda: None,
    )


def test_pipeline_runs_stage_list_in_order():
    workflow = [item("a", _workflow_index=0), item("b", _workflow_index=1)]
    ctx = context(workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["a", "b"]
    assert ctx.state.workflow_position == 2


def test_recover_is_flow_node_routing_and_retries_original_stage():
    review = item("review", recover=[item("repair")])
    workflow = [review]
    ctx = context(workflow)
    failed = False

    def callback(stage, *_):
        nonlocal failed
        if stage.name == "review" and not failed:
            failed = True
            return StageResult("review", "fail")
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["review", "repair", "review"]


def test_recover_receives_failed_stage_structured_data():
    workflow = [item("review", recover=[item("repair")])]
    ctx = context(workflow)
    failed = False

    def callback(stage, _ctx, previous):
        nonlocal failed
        if stage.name == "review" and not failed:
            failed = True
            return StageResult(
                "review",
                "fail",
                data={"completed": False, "reason": "missing", "missing_items": ["A"]},
            )
        if stage.name == "repair":
            assert previous.data["missing_items"] == ["A"]
        return StageResult(stage.name, "pass")

    Pipeline(ctx, workflow).run(Executor(callback))


def test_restart_at_is_owned_by_flow_node():
    workflow = [
        item("repair", _workflow_index=0),
        item("validate", restart_at="repair", _workflow_index=1),
    ]
    ctx = context(workflow)
    failed = False

    def callback(stage, *_):
        nonlocal failed
        if stage.name == "validate" and not failed:
            failed = True
            return StageResult("validate", "fail")
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["repair", "validate", "repair", "validate"]


def test_generated_steps_run_as_generic_child_flow():
    tasks = [
        Task("t1", "one", "d", ["a"], "o", steps=["execute", "review"]),
        Task("t2", "two", "d", ["a"], "o", steps=["execute", "review"]),
        Task("t3", "three", "d", ["a"], "o", steps=["execute", "review"]),
    ]
    workflow = [item("planning", _workflow_index=0)]
    ctx = context(workflow)
    next_steps = []
    for task_index in range(3):
        next_steps.extend([
            item("execute", _task_index=task_index, _task_last=False),
            item("review", _task_index=task_index, _task_last=True),
        ])

    def callback(stage, ctx, _previous):
        if stage.name == "planning":
            ctx.state.tasks = list(tasks)
            ctx.state.current = 0
            return StageResult(stage.name, "pass", data=tasks, next_steps=next_steps)
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == [
        "planning",
        "execute", "review",
        "execute", "review",
        "execute", "review",
    ]
    assert ctx.state.current == 3
    assert ctx.state.dynamic_steps == []
    assert ctx.state.workflow_position == 1

