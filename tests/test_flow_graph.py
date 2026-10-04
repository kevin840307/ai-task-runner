from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import runner.workflow.flow_engine as flow_engine_module
from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState
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


def node(name, **extra):
    return {"name": name, "type": "fake", **extra}


class Executor:
    def __init__(self, callback):
        self.callback = callback
        self.seen = []
        self.labels = []

    def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
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


def test_run_completion_clears_only_stale_technical_state(tmp_path):
    workflow = [node("only")]
    ctx = context(tmp_path, workflow)
    ctx.state.stage_sessions = {"only": "session-1"}
    ctx.state.review_failures = {"only::__run__": 2}
    ctx.state.dynamic_groups = {"producer": "producer__g1"}
    ctx.state.dynamic_task_groups = {"producer": ["producer__g1__task"]}
    ctx.state.transition_history = [{
        "stage": "previous",
        "status": "pass",
        "target": "only",
        "cycle": 1,
        "kind": "generic",
        "timestamp": 1.0,
    }]

    assert FlowEngine(ctx).run(
        Executor(lambda stage, *_: StageResult(stage.name, "pass"))
    ) == 0

    assert ctx.state.completed is True
    assert ctx.state.stage_sessions == {}
    assert ctx.state.review_failures == {}
    assert ctx.state.dynamic_groups == {}
    assert ctx.state.dynamic_task_groups == {}
    # Bounded semantic history remains useful after completion.
    assert ctx.state.transition_history


def test_done_edge_completes_immediately(tmp_path):
    workflow = [node("gate", routes={"pass": "done"}), node("never")]
    ctx = context(tmp_path, workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))

    assert FlowEngine(ctx).run(executor) == 0
    assert executor.seen == ["gate"]
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



def _task(task_id: str):
    from runner.runtime.run_state import Task
    return Task(
        id=task_id,
        title=task_id,
        description=f"work {task_id}",
        deliverable="artifact",
        acceptance_criteria=["done"],
    )


def test_dynamic_children_execute_before_parent_continuation(tmp_path):
    workflow = [
        node("a"),
        node("producer", produces="tasks"),
        node("d"),
    ]
    ctx = context(tmp_path, workflow)

    def callback(stage, _ctx, previous):
        if stage.name == "producer":
            return StageResult(
                "producer",
                "pass",
                kind="tasks",
                data={
                    "tasks": [_task("t1")],
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
                            "routes": {"fail": "execute"},
                        },
                    ],
                },
            )
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == [
        "a",
        "producer",
        "producer__g1__execute",
        "producer__g1__review",
        "d",
    ]
    assert ctx.state.tasks and ctx.state.tasks[0].status == "completed"
    assert ctx.state.completed is True
    assert [item["name"] for item in ctx.state.expanded_workflow] == executor.seen


def test_dynamic_review_fail_loops_inside_child_before_parent_continues(tmp_path):
    workflow = [node("producer", produces="tasks"), node("after")]
    ctx = context(tmp_path, workflow)
    review_calls = 0

    def callback(stage, _ctx, previous):
        nonlocal review_calls
        if stage.name == "producer":
            return StageResult(
                "producer",
                "pass",
                kind="tasks",
                data={
                    "tasks": [_task("work")],
                    "stages": [
                        {
                            "name": "execute",
                            "type": "base",
                            "profile": "execute",
                            "task_id": "work",
                        },
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
        if stage.name.endswith("__review"):
            review_calls += 1
            if review_calls == 1:
                return StageResult(
                    stage.name,
                    "fail",
                    data={"completed": False, "missing_items": ["fix"]},
                    kind="review",
                )
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == [
        "producer",
        "producer__g1__execute",
        "producer__g1__review",
        "producer__g1__execute",
        "producer__g1__review",
        "after",
    ]
    assert ctx.state.tasks[0].status == "completed"


def test_nested_dynamic_producer_returns_to_outer_child_then_parent(tmp_path):
    workflow = [node("producer", produces="stages"), node("after")]
    ctx = context(tmp_path, workflow)

    def callback(stage, _ctx, previous):
        if stage.name == "producer":
            return StageResult(
                "producer",
                "pass",
                kind="stages",
                data={
                    "stages": [
                        {
                            "name": "nested",
                            "type": "base",
                            "profile": "generic",
                            "produces": "stages",
                        },
                        {"name": "outer_tail", "type": "base", "profile": "generic"},
                    ]
                },
            )
        if stage.name.endswith("__nested"):
            return StageResult(
                stage.name,
                "pass",
                kind="stages",
                data={
                    "stages": [
                        {"name": "nested_child", "type": "base", "profile": "generic"}
                    ]
                },
            )
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == [
        "producer",
        "producer__g1__nested",
        "producer__g1__nested__g2__nested_child",
        "producer__g1__outer_tail",
        "after",
    ]


def test_resume_uses_durable_expanded_workflow_without_rerunning_producer(tmp_path):
    workflow = [node("producer", produces="stages"), node("after")]
    ctx = context(tmp_path, workflow)
    from runner.workflow.dynamic_expansion import expand_stage_result

    expanded = expand_stage_result(
        state=ctx.state,
        workflow=workflow,
        source_index=0,
        source=workflow[0],
        result=StageResult(
            "producer",
            "pass",
            kind="stages",
            data={"stages": [{"name": "child", "type": "base", "profile": "generic"}]},
        ),
        continuation="next",
    )
    assert expanded is not None
    ctx.state.workflow_position = 1
    ctx.state.transition_previous = {
        "stage": "producer",
        "status": "pass",
        "output": "durable producer output",
        "changed_files": [],
        "data": None,
        "kind": "stages",
    }

    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))
    assert FlowEngine(ctx).run(executor) == 0

    assert executor.seen == ["producer__g1__child", "after"]
    assert "producer" not in executor.seen



def test_dynamic_reexpansion_releases_old_role_client_cache(tmp_path):
    workflow = [
        node("producer", produces="stages"),
        node("gate", routes={"fail": "producer"}),
    ]
    ctx = context(tmp_path, workflow)
    producer_calls = 0
    gate_calls = 0
    checked = False

    def callback(stage, _ctx, previous):
        nonlocal producer_calls, gate_calls, checked
        if stage.name == "producer":
            producer_calls += 1
            return StageResult(
                "producer",
                "pass",
                kind="stages",
                data={
                    "stages": [{
                        "name": "role",
                        "type": "base",
                        "profile": "generic",
                        "session_policy": "role",
                    }]
                },
            )
        if stage.name == "producer__g1__role":
            _ctx.state.stage_sessions[stage.name] = "session-old"
            _ctx.scratch[f"stage_session:{stage.name}"] = object()
            return StageResult(stage.name, "pass")
        if stage.name == "gate":
            gate_calls += 1
            return StageResult(stage.name, "fail" if gate_calls == 1 else "pass")
        if stage.name == "producer__g2__role":
            checked = True
            assert "producer__g1__role" not in _ctx.state.stage_sessions
            assert "stage_session:producer__g1__role" not in _ctx.scratch
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    assert FlowEngine(ctx).run(executor) == 0
    assert producer_calls == 2
    assert checked is True



def test_transition_history_records_actual_semantic_targets(tmp_path):
    workflow = [
        node("work"),
        node("review", routes={"fail": "work"}),
        node("done"),
    ]
    ctx = context(tmp_path, workflow)
    reviews = 0

    def callback(stage, _ctx, previous):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            return StageResult(
                "review",
                "fail" if reviews == 1 else "pass",
                kind="review",
            )
        return StageResult(stage.name, "pass")

    assert FlowEngine(ctx).run(Executor(callback)) == 0

    compact = [
        (item["stage"], item["status"], item["target"])
        for item in ctx.state.transition_history
    ]
    assert compact == [
        ("work", "pass", "review"),
        ("review", "fail", "work"),
        ("work", "pass", "review"),
        ("review", "pass", "done"),
        ("done", "pass", "done"),
    ]


def test_transition_history_is_bounded_for_long_running_loops(tmp_path):
    workflow = [
        node("work"),
        node("review", routes={"fail": "work"}),
    ]
    ctx = context(tmp_path, workflow)
    ctx.config.max_cycles = 25
    reviews = 0

    def callback(stage, _ctx, previous):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            if reviews < 25:
                return StageResult("review", "fail", kind="review")
        return StageResult(stage.name, "pass")

    assert FlowEngine(ctx).run(Executor(callback)) == 0

    assert len(ctx.state.transition_history) == 40
    assert ctx.state.transition_history[-1]["stage"] == "review"
    assert ctx.state.transition_history[-1]["status"] == "pass"
    assert all(set(item) == {"stage", "status", "target", "cycle", "kind", "timestamp"} for item in ctx.state.transition_history)
