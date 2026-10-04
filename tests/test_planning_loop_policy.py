from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runner.agent import AIError, BackendError
from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState
from runner.workflow.stages import StageContext, StageResult
from runner.workflow.execution import StageExecutor


class Hooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback()


def loop_error(message: str) -> AIError:
    backend = BackendError(
        message,
        return_code=1,
        diagnostics={"loop_type": "consecutive_identical_tool_calls"},
    )
    error = AIError(message)
    error.__cause__ = backend
    return error


class PlanningStage:
    name = "planning"
    status = "Planning"
    detail = ""
    run_state = "planning"
    mode = "readonly"
    actor = "ai"
    track_changes = False
    tolerate_restored_changes = False
    fresh_session_on_start = False

    def __init__(self):
        self.calls = 0
        self.retry_modes = []

    def run(self, ctx, previous=None):
        self.calls += 1
        self.retry_modes.append(ctx.execution.retry_mode)
        if self.calls <= 2:
            raise loop_error(f"loop attempt {self.calls}")
        return StageResult(self.name, "pass", output="planned")

    def finish(self, ctx, result):
        return result


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    model = SimpleNamespace(session_id="planning-session")
    return StageContext(
        config=RuntimeConfig(
            stage_retries=2,
            retry_delay=0,
            retry_max_delay=0,
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=model,
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_planning_uses_the_same_two_attempt_session_rotation_as_every_stage(tmp_path):
    stage = PlanningStage()
    ctx = context(tmp_path)

    result = StageExecutor(Hooks()).run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == 3
    assert stage.retry_modes == ["initial", "retry", "recover"]
    assert ctx.ai_client.session_id == ""


def test_stage_executor_has_no_planning_specific_retry_policy():
    assert not hasattr(StageExecutor, "_same_session_retry_limit")
    assert not hasattr(StageExecutor, "_failure_key")


def test_plan_generated_children_inherit_backend_model_without_parent_session_policy():
    from runner.runtime.run_state import Task
    from runner.workflow.stages.plan_stage import PlanStage

    tasks = [
        Task(
            id="t1",
            title="Task",
            description="Do work",
            acceptance_criteria=["done"],
            deliverable="result",
        )
    ]

    children = PlanStage._plan_child_stages(
        tasks,
        backend="opencode",
        model="provider/model-x",
    )

    assert len(children) == 2
    assert all(child["backend"] == "opencode" for child in children)
    assert all(child["model"] == "provider/model-x" for child in children)
    assert all("session_policy" not in child for child in children)


def test_plan_generated_children_keep_global_backend_when_no_override():
    from runner.runtime.run_state import Task
    from runner.workflow.stages.plan_stage import PlanStage

    tasks = [
        Task(
            id="t1",
            title="Task",
            description="Do work",
            acceptance_criteria=["done"],
            deliverable="result",
        )
    ]

    children = PlanStage._plan_child_stages(tasks)

    assert all("backend" not in child for child in children)
    assert all("model" not in child for child in children)
