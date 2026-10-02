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
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
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
