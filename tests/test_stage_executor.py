from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import ConfigurationError, RunnerError
from runner.runtime import events
from runner.runtime.events import EventBus
from runner.runtime.run_state import RunState
from runner.workflow.execution import StageExecutor
from runner.workflow.stages import StageResult
from runner.workflow.stages import StageContext


class Hooks:
    def __init__(self):
        self.calls = []

    def before(self, action):
        self.calls.append(("before", action.name))
        return []

    def after(self, action, tokens):
        self.calls.append(("after", action.name))
        return []

    def change_detector(self, action, tokens, base):
        return base


class Stage:
    name = "sample"
    status = "Sample"
    detail = ""
    run_state = ""
    mode = "readonly"
    actor = "test"
    tolerate_restored_changes = False
    track_changes = False
    fresh_session_on_start = False

    def run(self, ctx, previous=None):
        return StageResult(self.name, "pass", output="ok")

    def finish(self, ctx, result):
        return result


def context(tmp_path=Path(".")):
    state = RunState("run", "goal", str(tmp_path))
    model = SimpleNamespace(session_id="")
    def set_stage(stage_name, detail=""):
        state.stage = stage_name
        state.last_error = detail

    return StageContext(
        config=RuntimeConfig(stage_retries=0, retry_delay=0, retry_max_delay=0),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=model,
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=set_stage,
    )


def test_executor_wraps_one_stage_once_with_hooks():
    hooks = Hooks()
    result = StageExecutor(hooks).run(Stage(), context())
    assert result.status == "pass"
    assert hooks.calls == [("before", "sample"), ("after", "sample")]


def test_executor_propagates_keyboard_interrupt_after_hook_cleanup():
    class Interrupted(Stage):
        def run(self, ctx, previous=None):
            raise KeyboardInterrupt()

    hooks = Hooks()
    with pytest.raises(KeyboardInterrupt):
        StageExecutor(hooks)._attempt(Interrupted(), context(), None)
    assert hooks.calls == [("before", "sample"), ("after", "sample")]


def test_executor_propagates_system_exit_from_finish():
    class ExitOnFinish(Stage):
        def finish(self, ctx, result):
            raise SystemExit(7)

    with pytest.raises(SystemExit) as error:
        StageExecutor(Hooks()).run(ExitOnFinish(), context())
    assert error.value.code == 7


def test_executor_converts_stage_exception_to_result():
    class Broken(Stage):
        def run(self, ctx, previous=None):
            raise RunnerError("boom")

    result = StageExecutor(Hooks())._attempt(Broken(), context(), None)
    assert result.status == "error"
    assert "boom" in str(result.error)


def test_executor_does_not_retry_configuration_error():
    class Broken(Stage):
        def run(self, ctx, previous=None):
            raise ConfigurationError("bad config")

    with pytest.raises(ConfigurationError, match="bad config"):
        StageExecutor(Hooks()).run(Broken(), context())


def test_executor_preserves_one_lifecycle_for_internal_retries():
    class RetryOnce(Stage):
        def __init__(self):
            self.calls = 0

        def run(self, ctx, previous=None):
            self.calls += 1
            if self.calls == 1:
                return StageResult.error_result(self.name, RunnerError("retry"))
            return StageResult(self.name, "pass")

    ctx = context()
    ctx.config.stage_retries = 1
    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)
    stage = RetryOnce()

    StageExecutor(Hooks()).run(stage, ctx)

    lifecycle = [
        (event["action"], event.get("stage"))
        for event in records
        if event["type"] == "runner.stage"
    ]
    assert stage.calls == 2
    assert lifecycle == [("start", "sample"), ("finish", "sample")]


def test_executor_persists_recovery_error_and_clears_it_after_success():
    class RetryOnce(Stage):
        def __init__(self):
            self.calls = 0

        def run(self, ctx, previous=None):
            self.calls += 1
            if self.calls == 1:
                return StageResult.error_result(self.name, RunnerError("HTTP 503"))
            return StageResult(self.name, "pass")

    ctx = context()
    ctx.config.stage_retries = 1
    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)

    result = StageExecutor(Hooks()).run(RetryOnce(), ctx)

    assert result.status == "pass"
    assert ctx.state.last_error == ""
    assert any(
        event["type"] == "runner.status"
        and event["action"] == "set"
        and event["status"] == "Recovering"
        and "retry 1" in event["detail"]
        and "wait 0s" in event["detail"]
        and "HTTP 503" in event["detail"]
        for event in records
    )
    recovery = next(
        event
        for event in records
        if event["type"] == "runner.recovery" and event["action"] == "retry"
    )
    assert recovery["stage"] == "sample"
    assert recovery["retry_mode"] in {"retry", "recover"}
    assert recovery["retry"] == 1
    assert recovery["wait_seconds"] == 0
    assert "HTTP 503" in recovery["error"]


def test_executor_keeps_final_technical_error_for_detached_ui():
    class Broken(Stage):
        def run(self, ctx, previous=None):
            return StageResult.error_result(self.name, RunnerError("permanent transport error"))

    ctx = context()
    ctx.config.stage_retries = 0

    result = StageExecutor(Hooks()).run(Broken(), ctx)

    assert result.status == "error"
    assert "permanent transport error" in ctx.state.last_error


def test_executor_uses_node_label_only_as_event_detail():
    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)
    StageExecutor(Hooks()).run(Stage(), context(), label="Project Documentation")
    start = next(
        event for event in records
        if event["type"] == "runner.stage" and event["action"] == "start"
    )
    assert start["stage"] == "sample"
    assert start["label"] == "Project Documentation"


def test_executor_preserves_explicit_dynamic_result_kind():
    class Dynamic(Stage):
        result_kind = "generic"

        def run(self, ctx, previous=None):
            return StageResult(
                self.name,
                "pass",
                data={"stages": [{"name": "child", "type": "base", "profile": "generic"}]},
                kind="stages",
            )

    result = StageExecutor(Hooks()).run(Dynamic(), context())
    assert result.kind == "stages"


def test_executor_fills_declared_kind_only_for_generic_result():
    class ReviewLike(Stage):
        result_kind = "review"

        def run(self, ctx, previous=None):
            return StageResult(self.name, "pass", data={"completed": True})

    result = StageExecutor(Hooks()).run(ReviewLike(), context())
    assert result.kind == "review"



def test_unlimited_retry_with_zero_configured_delay_uses_safety_floor(monkeypatch):
    class RetryTwice(Stage):
        def __init__(self):
            self.calls = 0

        def run(self, ctx, previous=None):
            self.calls += 1
            if self.calls <= 2:
                return StageResult.error_result(self.name, RunnerError("temporary failure"))
            return StageResult(self.name, "pass")

    ctx = context()
    ctx.config.stage_retries = -1
    ctx.config.retry_delay = 0
    ctx.config.retry_max_delay = 0
    sleeps = []
    monkeypatch.setattr(StageExecutor, "_sleep", staticmethod(lambda _ctx, seconds: sleeps.append(seconds)))

    result = StageExecutor(Hooks()).run(RetryTwice(), ctx)

    assert result.status == "pass"
    assert sleeps == [1.0, 1.0]


def test_finite_retry_may_still_use_zero_delay(monkeypatch):
    class RetryOnce(Stage):
        def __init__(self):
            self.calls = 0

        def run(self, ctx, previous=None):
            self.calls += 1
            if self.calls == 1:
                return StageResult.error_result(self.name, RunnerError("retry immediately"))
            return StageResult(self.name, "pass")

    ctx = context()
    ctx.config.stage_retries = 1
    ctx.config.retry_delay = 0
    ctx.config.retry_max_delay = 0
    sleeps = []
    monkeypatch.setattr(StageExecutor, "_sleep", staticmethod(lambda _ctx, seconds: sleeps.append(seconds)))

    result = StageExecutor(Hooks()).run(RetryOnce(), ctx)

    assert result.status == "pass"
    assert sleeps == [0.0]
