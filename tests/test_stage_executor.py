from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.ai.errors import AIError
from runner.errors import RunnerError
from runner.runtime import events
from runner.runtime.events import EventBus
from runner.workflow.stages import StageExecutor, StageResult


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
    run_state = "sample"
    mode = "readonly"
    actor = "test"
    tolerate_restored_changes = False
    retry = 0

    def run(self, ctx, previous=None):
        return StageResult(self.name, "pass", output="ok")

    def finish(self, ctx, result):
        return result


def context():
    model = SimpleNamespace(session_id="")
    return SimpleNamespace(
        root=Path("."),
        work=Path("."),
        execution=SimpleNamespace(change_detected=None),
        set_stage=lambda *args: None,
        config=SimpleNamespace(stage_retry_delay=0),
        task=None,
        ai_client=model,
        scratch={},
        state=SimpleNamespace(
            ai_session_id="",
            failure_scope="",
            failure_key="",
            same_failures=0,
            fresh_session_round=0,
        ),
        save_state=lambda: None,
        reset_sessions=lambda: setattr(model, "session_id", ""),
    )




def test_timeout_recovery_key_ignores_dynamic_backend_output():
    executor = StageExecutor(Hooks())
    ctx = context()
    first = AIError(
        "qwen timed out after 1 seconds:\nContainerName (regular): qwen-code-0.21.0-20",
        recovery_key="qwen:timeout:1",
    )
    second = AIError(
        "qwen timed out after 1 seconds:\nContainerName (regular): qwen-code-0.21.0-51",
        recovery_key="qwen:timeout:1",
    )
    assert executor._failure_key(Stage(), ctx, first) == executor._failure_key(
        Stage(), ctx, second
    )


def test_different_semantic_recovery_keys_stay_different():
    executor = StageExecutor(Hooks())
    ctx = context()
    one = AIError("timeout", recovery_key="qwen:timeout:1")
    two = AIError("timeout", recovery_key="qwen:timeout:2")
    assert executor._failure_key(Stage(), ctx, one) != executor._failure_key(
        Stage(), ctx, two
    )

def test_executor_wraps_one_stage_once_with_hooks():
    hooks = Hooks()
    executor = StageExecutor(hooks)
    result = executor.run(Stage(), context())
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


def test_executor_preserves_stage_lifecycle_events():
    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)
    StageExecutor(Hooks()).run(Stage(), context())
    lifecycle = [
        (event["type"], event["action"], event.get("stage"))
        for event in records
        if event["type"] == "runner.stage"
    ]
    assert lifecycle == [
        ("runner.stage", "start", "sample"),
        ("runner.stage", "finish", "sample"),
    ]


def test_executor_exposes_flow_label_as_event_detail_without_changing_stage_status():
    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)
    StageExecutor(Hooks()).run(Stage(), context(), label="Project Documentation")

    start = next(
        event for event in records
        if event["type"] == "runner.stage" and event["action"] == "start"
    )
    status = next(
        event for event in records
        if event["type"] == "runner.status" and event["action"] == "start"
    )
    assert start["stage"] == "sample"
    assert start["label"] == "Project Documentation"
    assert status["status"] == "Sample"
    assert status["detail"] == "Project Documentation"


def test_executor_does_not_restart_stage_lifecycle_for_retries():
    class RetryOnce(Stage):
        retry = 1

        def __init__(self):
            self.calls = 0

        def run(self, ctx, previous=None):
            self.calls += 1
            if self.calls == 1:
                return StageResult.error_result(self.name, RunnerError("retry"))
            return StageResult(self.name, "pass")

    records = []
    bus = EventBus()
    bus.subscribe(records.append)
    events.configure(bus)
    StageExecutor(Hooks()).run(RetryOnce(), context())
    lifecycle = [
        (event["action"], event.get("stage"))
        for event in records
        if event["type"] == "runner.stage"
    ]
    assert lifecycle == [("start", "sample"), ("finish", "sample")]


def test_hook_chain_rolls_back_completed_before_hooks_when_later_before_fails():
    from runner.plugins.contracts import HookChain

    calls = []

    class First:
        def before_execution(self, action):
            calls.append("first.before")
            return "token"

        def after_execution(self, action, token):
            calls.append(("first.after", token))
            return []

    class Second:
        def before_execution(self, action):
            calls.append("second.before")
            raise RunnerError("blocked")

        def after_execution(self, action, token):
            calls.append("second.after")
            return []

    chain = HookChain()
    chain.add(First())
    chain.add(Second())
    try:
        chain.before(SimpleNamespace())
    except RunnerError:
        pass
    assert calls == ["first.before", "second.before", ("first.after", "token")]


def test_base_stage_fresh_session_resets_only_its_cached_client():
    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec

    ctx = context()
    ctx.ai_client.session_id = "writer-session"
    review = SimpleNamespace(session_id="review-session")
    ctx.scratch["review_client"] = review
    ctx.scratch["prompt_contracts"] = {
        ("review.md", "review-session"),
        ("execution.md", "writer-session"),
    }
    stage = BaseStage(
        BaseStageSpec(
            name="review",
            status="Review",
            prompt="review.md",
            client_cache_key="review_client",
        )
    )

    StageExecutor(Hooks()).fresh_session(stage, ctx)

    assert review.session_id == ""
    assert ctx.ai_client.session_id == "writer-session"
    assert ("review.md", "review-session") not in ctx.scratch["prompt_contracts"]
    assert ("execution.md", "writer-session") in ctx.scratch["prompt_contracts"]
