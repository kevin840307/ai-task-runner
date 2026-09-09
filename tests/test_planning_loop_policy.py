from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runner.ai.errors import AIError, BackendError
from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState, Task
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor


class Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback()


class PlanningStage:
    name = "planning"
    status = "Planning"
    detail = ""
    run_state = "planning"
    mode = "readonly"
    actor = "ai"
    retry = None
    skip_on_error = False
    track_changes = False
    tolerate_restored_changes = False
    result_kind = "tasks"

    def __init__(self):
        self.calls = 0
        self.retry_modes: list[str] = []

    def run(self, ctx, previous=None):
        self.calls += 1
        self.retry_modes.append(ctx.execution.retry_mode)
        if self.calls <= 2:
            raise planning_loop_error(
                f"qwen loop attempt {self.calls} dynamic-turn={40 + self.calls}",
                "consecutive_identical_tool_calls",
            )
        return StageResult(
            self.name,
            "pass",
            data=[Task("t1", "Do task", "Do the requested work", "artifact", ["done"])],
        )

    def finish(self, ctx, result): return result

    def reset_session(self, ctx):
        previous = ctx.ai_client.session_id
        ctx.ai_client.session_id = ""
        return previous


def planning_loop_error(message: str, loop_type: str) -> AIError:
    backend = BackendError(
        message,
        return_code=1,
        diagnostics={"loop_type": loop_type, "num_turns": 42},
    )
    error = AIError(message)
    error.__cause__ = backend
    return error


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    ai = SimpleNamespace(session_id="planning-session-1")
    work = tmp_path / ".work"
    work.mkdir(exist_ok=True)
    return StageContext(
        config=RuntimeConfig(same_session_retries=5, stage_retry_delay=0),
        root=tmp_path,
        work=work,
        state=state,
        ai_client=ai,
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=False,
        scratch={},
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_planning_loop_caps_same_session_retry_to_one():
    stage = PlanningStage()
    error = planning_loop_error("loop", "consecutive_identical_tool_calls")
    assert StageExecutor._same_session_retry_limit(stage, error, 5) == 1


def test_planning_loop_failure_key_ignores_dynamic_backend_noise(tmp_path: Path):
    stage = PlanningStage()
    ctx = context(tmp_path)
    first = planning_loop_error("dynamic turn=41", "turn_tool_call_cap")
    second = planning_loop_error("dynamic turn=99", "turn_tool_call_cap")
    assert StageExecutor._failure_key(stage, ctx, first) == StageExecutor._failure_key(
        stage, ctx, second
    )


def test_non_planning_stage_keeps_generic_retry_budget():
    stage = PlanningStage()
    stage.result_kind = "review"
    error = planning_loop_error("loop", "consecutive_identical_tool_calls")
    assert StageExecutor._same_session_retry_limit(stage, error, 5) == 5


def test_planning_repeated_loop_rotates_fresh_after_one_same_session_retry(tmp_path: Path):
    stage = PlanningStage()
    ctx = context(tmp_path)
    fresh_sessions: list[str] = []
    executor = StageExecutor(Hooks())
    def capture_fresh(current_ctx):
        fresh_sessions.append(current_ctx.ai_client.session_id)
        current_ctx.ai_client.session_id = ""

    executor._fresh_session = capture_fresh
    result = executor.run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == 3
    assert stage.retry_modes == ["initial", "same", "fresh"]
    assert fresh_sessions == ["planning-session-1"]


class AlwaysLoopPlanningStage(PlanningStage):
    def run(self, ctx, previous=None):
        self.calls += 1
        self.retry_modes.append(ctx.execution.retry_mode)
        raise planning_loop_error(
            f"qwen loop attempt {self.calls} dynamic-turn={70 + self.calls}",
            "consecutive_identical_tool_calls",
        )


def test_planning_loop_stops_after_same_then_fresh_instead_of_replanning_forever(tmp_path: Path):
    stage = AlwaysLoopPlanningStage()
    ctx = context(tmp_path)
    executor = StageExecutor(Hooks())

    result = executor.run(stage, ctx)

    assert result.status == "error"
    assert stage.calls == 3
    assert stage.retry_modes == ["initial", "same", "fresh"]
    assert ctx.state.fresh_session_round == 1
    assert ctx.state.same_failures == 3
