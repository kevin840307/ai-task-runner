from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import runner.workflow.flow_engine as flow_engine_module
from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState, Task
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.stages import StageContext, StageResult


class Stage:
    mode = "readonly"
    actor = "test"
    status = "test"
    detail = ""
    track_changes = False
    tolerate_restored_changes = False
    fresh_session_on_start = False

    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def stage_factory(monkeypatch):
    monkeypatch.setattr(
        flow_engine_module, "create_stage", lambda item: Stage(item["name"])
    )
    monkeypatch.setattr(
        flow_engine_module, "stage_result_kind", lambda item: str(item.get("produces") or "generic")
    )


def node(name, **extra):
    return {"name": name, "type": "fake", **extra}


class Executor:
    def __init__(self, callback):
        self.callback = callback
        self.seen = []
        self.labels = []

    def run(self, stage, ctx, previous=None, *, label=""):
        self.seen.append(stage.name)
        self.labels.append(label)
        return self.callback(stage, ctx, previous)


def context(tmp_path: Path, workflow, tasks=None):
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=list(tasks or []),
    )
    return StageContext(
        config=RuntimeConfig(
            goal="goal",
            project_root=str(tmp_path),
            workflow=workflow,
            workflow_explicit=True,
            stage_retries=0,
            retry_delay=0,
            retry_max_delay=0,
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=SimpleNamespace(session_id=""),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_pass_runs_string_flow_in_order_and_forwards_label(tmp_path):
    workflow = [node("a", label="Project Documentation"), node("b")]
    ctx = context(tmp_path, workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))

    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == ["a", "b"]
    assert executor.labels == ["Project Documentation", ""]
    assert ctx.state.workflow_position == 2
    assert ctx.state.completed is True


def test_fail_edge_is_the_only_closed_loop_mechanism(tmp_path):
    workflow = [
        node("work"),
        node("review", routes={"fail": "work"}),
    ]
    ctx = context(tmp_path, workflow)
    reviews = 0

    def callback(stage, _ctx, previous):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            if reviews == 1:
                return StageResult(
                    "review",
                    "fail",
                    output="missing A",
                    data={"missing_items": ["A"]},
                )
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0
    assert executor.seen == ["work", "review", "work", "review"]


def test_routed_stage_receives_previous_structured_result(tmp_path):
    workflow = [
        node("review", routes={"fail": "repair"}),
        node("repair"),
    ]
    ctx = context(tmp_path, workflow)
    seen = {}

    def callback(stage, _ctx, previous):
        if stage.name == "review":
            return StageResult(
                "review",
                "fail",
                output="missing",
                data={"missing_items": ["A"]},
            )
        seen["previous"] = previous
        return StageResult("repair", "pass")

    assert FlowEngine(ctx).run(Executor(callback)) == 0
    assert seen["previous"].data == {"missing_items": ["A"]}


@pytest.mark.parametrize("status", ["fail", "error"])
def test_unrouted_non_pass_stops_without_advancing(tmp_path, status):
    workflow = [node("gate")]
    ctx = context(tmp_path, workflow)

    code = FlowEngine(ctx).run(
        Executor(lambda stage, *_: StageResult(stage.name, status))
    )

    assert code == 1
    assert ctx.state.workflow_position == 0
    assert ctx.state.completed is False


def test_done_edge_completes_immediately(tmp_path):
    workflow = [node("gate", routes={"pass": "done"}), node("never")]
    ctx = context(tmp_path, workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))

    assert FlowEngine(ctx).run(executor) == 0
    assert executor.seen == ["gate"]
    assert ctx.state.completed is True


def test_task_scope_runs_the_explicit_block_for_each_task(tmp_path):
    tasks = [
        Task("t1", "one", "d", ["a"], "o"),
        Task("t2", "two", "d", ["a"], "o"),
    ]
    workflow = [
        node("execute", scope="task"),
        node("review", scope="task"),
        node("validate"),
    ]
    ctx = context(tmp_path, workflow, tasks)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))

    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == [
        "execute", "review",
        "execute", "review",
        "validate",
    ]
    assert ctx.state.current == 2
    assert all(task.status == "completed" for task in ctx.state.tasks)
    assert ctx.state.completed is True


def test_task_review_fail_edge_restarts_same_task_at_execute(tmp_path):
    task = Task("t1", "one", "d", ["a"], "o")
    workflow = [
        node("execute", scope="task"),
        node("review", scope="task", routes={"fail": "execute"}),
    ]
    ctx = context(tmp_path, workflow, [task])
    reviews = 0

    def callback(stage, _ctx, previous):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            return StageResult(stage.name, "fail" if reviews == 1 else "pass")
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0
    assert executor.seen == ["execute", "review", "execute", "review"]
    assert ctx.state.current == 1
    assert ctx.state.completed is True


def test_latest_transition_is_restored_on_resume(tmp_path):
    workflow = [node("first"), node("second")]
    ctx = context(tmp_path, workflow)
    ctx.state.workflow_position = 1
    ctx.state.transition_previous = {
        "stage": "first",
        "status": "pass",
        "output": "durable feedback",
        "changed_files": [],
        "data": {"evidence": "saved"},
        "kind": "generic",
    }
    seen = {}

    def callback(stage, _ctx, previous):
        seen["previous"] = previous
        return StageResult(stage.name, "pass")

    assert FlowEngine(ctx).run(Executor(callback)) == 0
    assert seen["previous"].stage == "first"
    assert seen["previous"].output == "durable feedback"
    assert seen["previous"].data == {"evidence": "saved"}
