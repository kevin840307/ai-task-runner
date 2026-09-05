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
        self.labels = []

    def run(self, stage, ctx, previous=None, *, label=""):
        self.seen.append(stage.name)
        self.labels.append(label)
        return self.callback(stage, ctx, previous)

    def fresh_session(self, stage, ctx):
        self.seen.append(f"fresh:{stage.name}")


def context(workflow, tasks=None):
    state = SimpleNamespace(
        completed=False,
        workflow_position=0,
        current=0,
        tasks=list(tasks or []),
        task_step=0,
        stage="created",
        validator_failure_key="",
        validator_failure_count=0,
        ai_session_id="",
        replan_feedback="",
        flow_result_key="",
        flow_result_count=0,
        flow_result_previous={},
        semantic_failure_key="",
        semantic_failure_fingerprint="",
        semantic_failure_count=0,
    )
    return SimpleNamespace(
        state=state,
        config=SimpleNamespace(workflow=workflow, max_cycles=10),
        ai_client=SimpleNamespace(session_id=""),
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
        reset_sessions=lambda: None,
    )


def test_pipeline_passes_optional_flow_label_without_changing_stage():
    workflow = [item("a", label="Project Documentation", _workflow_index=0)]
    ctx = context(workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["a"]
    assert executor.labels == ["Project Documentation"]


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


def test_task_scoped_stages_run_for_each_planned_todo():
    tasks = [
        Task("t1", "one", "d", ["a"], "o"),
        Task("t2", "two", "d", ["a"], "o"),
        Task("t3", "three", "d", ["a"], "o"),
    ]
    workflow = [
        item("planning", _workflow_index=0),
        item("execute", scope="task", _workflow_index=1),
        item("review", scope="task", _workflow_index=2),
    ]
    ctx = context(workflow)

    def callback(stage, ctx, _previous):
        if stage.name == "planning":
            ctx.state.tasks = list(tasks)
            ctx.state.current = 0
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
    assert ctx.state.task_step == 0
    assert ctx.state.workflow_position == 3

def test_repeat_is_opt_in_and_default_recovery_is_unchanged():
    workflow = [item("review", recover=[item("repair")])]
    ctx = context(workflow)
    failures = 0

    def callback(stage, *_):
        nonlocal failures
        if stage.name == "review" and failures < 3:
            failures += 1
            return StageResult("review", "fail")
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["review", "repair"] * 3 + ["review"]
    assert ctx.state.flow_result_count == 0


def test_repeat_counts_only_semantic_results_and_stops_after_final_recover():
    workflow = [
        item("grill", repeat=3, recover=[item("fix")], _workflow_index=0),
        item("next", _workflow_index=1),
    ]
    ctx = context(workflow)
    calls = 0

    def callback(stage, *_):
        nonlocal calls
        if stage.name == "grill":
            calls += 1
            return StageResult("grill", "fail", data={"completed": False})
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert calls == 3
    assert executor.seen == ["grill", "fix", "grill", "fix", "grill", "fix", "next"]
    assert ctx.state.workflow_position == 2
    assert ctx.state.flow_result_key == ""
    assert ctx.state.flow_result_count == 0


def test_repeat_pass_finishes_immediately():
    workflow = [item("grill", repeat=3, recover=[item("fix")], _workflow_index=0)]
    ctx = context(workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "pass"))
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["grill"]
    assert ctx.state.flow_result_count == 0


def test_repeat_survives_crash_and_resume():
    workflow = [
        item("grill", repeat=3, recover=[item("fix")], _workflow_index=0),
        item("next", _workflow_index=1),
    ]
    ctx = context(workflow)
    crashed = False

    def first(stage, *_):
        nonlocal crashed
        if stage.name == "grill":
            return StageResult("grill", "fail")
        if stage.name == "fix" and not crashed:
            crashed = True
            raise KeyboardInterrupt
        return StageResult(stage.name, "pass")

    with pytest.raises(KeyboardInterrupt):
        Pipeline(ctx, workflow).run(Executor(first))
    assert ctx.state.flow_result_count == 1
    assert ctx.state.flow_result_key == "workflow:0"

    grill_calls = 0
    def resumed(stage, *_):
        nonlocal grill_calls
        if stage.name == "grill":
            grill_calls += 1
            return StageResult("grill", "fail")
        return StageResult(stage.name, "pass")

    executor = Executor(resumed)
    Pipeline(ctx, workflow).run(executor)
    assert grill_calls == 2
    assert executor.seen == ["grill", "fix", "grill", "fix", "next"]
    assert ctx.state.flow_result_count == 0


def test_repeat_does_not_count_non_semantic_error_result():
    workflow = [
        item("grill", repeat=3, recover=[item("fix")], _workflow_index=0),
        item("next", _workflow_index=1),
    ]
    ctx = context(workflow)
    executor = Executor(lambda stage, *_: StageResult(stage.name, "error"))
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == ["grill"]
    assert ctx.state.flow_result_key == ""
    assert ctx.state.flow_result_count == 0


def test_repeat_does_not_count_exception_before_semantic_result():
    workflow = [
        item("grill", repeat=3, recover=[item("fix")], _workflow_index=0),
        item("next", _workflow_index=1),
    ]
    ctx = context(workflow)

    def callback(stage, *_):
        raise RuntimeError("transport failure")

    with pytest.raises(RuntimeError, match="transport failure"):
        Pipeline(ctx, workflow).run(Executor(callback))
    assert ctx.state.flow_result_key == ""
    assert ctx.state.flow_result_count == 0


def test_repeat_resume_after_final_failure_retries_recover_not_challenge():
    workflow = [
        item("grill", repeat=3, recover=[item("fix")], _workflow_index=0),
        item("next", _workflow_index=1),
    ]
    ctx = context(workflow)
    grill_calls = 0
    fix_calls = 0

    def first(stage, *_):
        nonlocal grill_calls, fix_calls
        if stage.name == "grill":
            grill_calls += 1
            return StageResult(
                "grill",
                "fail",
                output=f"failure-{grill_calls}",
                data={"missing_items": [f"gap-{grill_calls}"]},
            )
        if stage.name == "fix":
            fix_calls += 1
            if fix_calls == 3:
                raise KeyboardInterrupt
            return StageResult("fix", "pass")
        return StageResult(stage.name, "pass")

    with pytest.raises(KeyboardInterrupt):
        Pipeline(ctx, workflow).run(Executor(first))
    assert grill_calls == 3
    assert ctx.state.flow_result_count == 3
    assert ctx.state.flow_result_previous["data"] == {"missing_items": ["gap-3"]}

    resumed_grills = 0
    recovered_feedback = []

    def resumed(stage, _ctx, previous=None):
        nonlocal resumed_grills
        if stage.name == "grill":
            resumed_grills += 1
        if stage.name == "fix":
            recovered_feedback.append(previous.data)
        return StageResult(stage.name, "pass")

    executor = Executor(resumed)
    Pipeline(ctx, workflow).run(executor)
    assert resumed_grills == 0
    assert executor.seen == ["fix", "next"]
    assert recovered_feedback == [{"missing_items": ["gap-3"]}]
    assert ctx.state.flow_result_count == 0
    assert ctx.state.flow_result_previous == {}


def test_repeated_same_semantic_failure_freshens_only_when_opted_in():
    workflow = [
        item(
            "review",
            fresh_after_same_failures=2,
            recover=[item("repair")],
            _workflow_index=0,
        )
    ]
    ctx = context(workflow)
    reviews = 0

    def callback(stage, *_):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            if reviews <= 2:
                return StageResult(
                    "review",
                    "fail",
                    data={
                        "completed": False,
                        "reason": "same verdict",
                        "missing_items": ["A"],
                    },
                )
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert executor.seen == [
        "review", "repair", "review", "fresh:review", "repair", "review"
    ]
    assert ctx.state.semantic_failure_count == 0


def test_semantic_fresh_is_opt_in_and_different_failures_reset_count():
    workflow = [item("review", recover=[item("repair")], _workflow_index=0)]
    ctx = context(workflow)
    results = iter([
        StageResult("review", "fail", data={"missing_items": ["A"]}),
        StageResult("review", "fail", data={"missing_items": ["A"]}),
        StageResult("review", "pass"),
    ])

    def callback(stage, *_):
        return next(results) if stage.name == "review" else StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)
    assert not any(name.startswith("fresh:") for name in executor.seen)
    assert ctx.state.semantic_failure_count == 0

    workflow = [item("review", fresh_after_same_failures=2, recover=[item("repair")], _workflow_index=0)]
    ctx = context(workflow)
    results = iter([
        StageResult("review", "fail", data={"missing_items": ["A"]}),
        StageResult("review", "fail", data={"missing_items": ["B"]}),
        StageResult("review", "pass"),
    ])
    executor = Executor(lambda stage, *_: next(results) if stage.name == "review" else StageResult(stage.name, "pass"))
    Pipeline(ctx, workflow).run(executor)
    assert not any(name.startswith("fresh:") for name in executor.seen)


def test_semantic_failure_count_survives_crash_before_next_review():
    workflow = [item("review", fresh_after_same_failures=2, recover=[item("repair")], _workflow_index=0)]
    ctx = context(workflow)

    def first(stage, *_):
        if stage.name == "review":
            return StageResult("review", "fail", data={"missing_items": ["A"]})
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        Pipeline(ctx, workflow).run(Executor(first))
    assert ctx.state.semantic_failure_count == 1

    reviews = 0
    def resumed(stage, *_):
        nonlocal reviews
        if stage.name == "review":
            reviews += 1
            if reviews == 1:
                return StageResult("review", "fail", data={"missing_items": ["A"]})
        return StageResult(stage.name, "pass")

    executor = Executor(resumed)
    Pipeline(ctx, workflow).run(executor)
    assert "fresh:review" in executor.seen
    assert ctx.state.semantic_failure_count == 0

def test_recovery_restarts_task_sop_only_after_actual_tasks_result():
    old = Task("old", "old", "d", ["a"], "o")
    new = Task("new", "new", "d", ["a"], "o")
    workflow = [
        item("execute", scope="task", _workflow_index=0),
        item(
            "validate",
            _workflow_index=1,
            recover=[item("generate", produces="tasks")],
        ),
    ]
    ctx = context(workflow, [old])
    failed = False

    def callback(stage, ctx, _previous):
        nonlocal failed
        if stage.name == "validate" and not failed:
            failed = True
            return StageResult("validate", "fail")
        if stage.name == "generate":
            ctx.state.tasks = [new]
            ctx.state.current = 0
            return StageResult("generate", "pass", kind="tasks")
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)

    assert executor.seen == ["execute", "validate", "generate", "execute", "validate"]
    assert ctx.state.current == 1
    assert ctx.state.completed is True


def test_recovery_does_not_restart_from_task_producer_declaration_alone():
    task = Task("t1", "one", "d", ["a"], "o")
    workflow = [
        item("execute", scope="task", _workflow_index=0),
        item(
            "validate",
            _workflow_index=1,
            recover=[item("generate", produces="tasks")],
        ),
    ]
    ctx = context(workflow, [task])
    failed = False

    def callback(stage, _ctx, _previous):
        nonlocal failed
        if stage.name == "validate" and not failed:
            failed = True
            return StageResult("validate", "fail")
        # Deliberately no tasks effect: Pipeline must react to the actual result,
        # not merely to the YAML declaration on this recovery node.
        return StageResult(stage.name, "pass")

    executor = Executor(callback)
    Pipeline(ctx, workflow).run(executor)

    assert executor.seen == ["execute", "validate", "generate", "validate"]
    assert ctx.state.current == 1
    assert ctx.state.completed is True

