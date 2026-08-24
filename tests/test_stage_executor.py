from pathlib import Path
from types import SimpleNamespace

from runner.errors import RunnerError
from runner.runtime import progress
from runner.runtime.progress import EventBus
from runner.flow.stages import StageExecutor, StageResult


class Hooks:
    def __init__(self): self.calls = []
    def before(self, action): self.calls.append(("before", action.name)); return []
    def after(self, action, tokens): self.calls.append(("after", action.name)); return []
    def change_detector(self, action, tokens, base): return base


class Stage:
    name = "sample"
    status = "Sample"
    detail = ""
    run_state = "sample"
    mode = "readonly"
    actor = "test"
    tolerate_restored_changes = False
    retry = 0
    def run(self, ctx, previous=None):
        return StageResult(self.name, "pass", output="ok")


def context():
    model = SimpleNamespace(session_id="")
    return SimpleNamespace(
        root=Path("."), work=Path("."),
        execution=SimpleNamespace(change_detected=None),
        set_stage=lambda *args: None,
        args=SimpleNamespace(retry_delay=0),
        task=None, model=model, scratch={},
        state=SimpleNamespace(
            model_session_id="", failure_scope="", failure_key="",
            same_failures=0, fresh_session_round=0,
        ),
        save_state=lambda: None,
    )


def test_executor_wraps_one_stage_once_with_hooks():
    hooks = Hooks(); executor = StageExecutor(hooks)
    result = executor.run(Stage(), context())
    assert result.status == "pass"
    assert hooks.calls == [("before", "sample"), ("after", "sample")]


def test_executor_converts_stage_exception_to_result():
    class Broken(Stage):
        def run(self, ctx, previous=None): raise RunnerError("boom")
    result = StageExecutor(Hooks()).run(Broken(), context())
    assert result.status == "error"
    assert "boom" in str(result.error)


def test_executor_preserves_stage_lifecycle_events():
    events = []
    bus = EventBus(); bus.subscribe(events.append)
    progress.configure(bus)
    StageExecutor(Hooks()).run(Stage(), context())
    lifecycle = [(event["type"], event["action"], event.get("stage")) for event in events if event["type"] == "runner.stage"]
    assert lifecycle == [("runner.stage", "start", "sample"), ("runner.stage", "finish", "sample")]


def test_hook_chain_rolls_back_completed_before_hooks_when_later_before_fails():
    from runner.extensions.base import HookChain

    calls = []

    class First:
        def before_execution(self, action): calls.append('first.before'); return 'token'
        def after_execution(self, action, token): calls.append(('first.after', token)); return []

    class Second:
        def before_execution(self, action): calls.append('second.before'); raise RunnerError('blocked')
        def after_execution(self, action, token): calls.append('second.after'); return []

    chain = HookChain(); chain.add(First()); chain.add(Second())
    try:
        chain.before(SimpleNamespace())
    except RunnerError:
        pass
    assert calls == ['first.before', 'second.before', ('first.after', 'token')]
