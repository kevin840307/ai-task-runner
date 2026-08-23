from __future__ import annotations

import pytest

from runner.agent.retry import retry_model_call
from runner.runtime import status as runner_status
from runner.runtime.events import EventBus
from runner.app.ui import LiveUI
from runner.engine.models import RunState, Task
from runner.errors import RunnerError


def _state() -> RunState:
    return RunState(run_id="r", goal="g", project_root=".", tasks=[Task(id="t1", title="one", description="one")])


def test_progress_event_is_not_repeated_for_same_state():
    events = []
    ui = LiveUI(event_callback=events.append, human_output=False)
    state = _state()
    ui.bind(state)
    ui.bind(state)
    assert [event["type"] for event in events] == ["runner.progress"]


def test_progress_event_emits_after_task_state_changes():
    events = []
    ui = LiveUI(event_callback=events.append, human_output=False)
    state = _state()
    ui.bind(state)
    state.tasks[0].attempts = 1
    ui.bind(state)
    assert [event["type"] for event in events] == ["runner.progress", "runner.progress"]


def test_final_failed_model_call_does_not_claim_it_will_retry():
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    runner_status.configure(bus)
    with pytest.raises(RunnerError):
        retry_model_call(
            lambda: (_ for _ in ()).throw(RunnerError("boom")),
            "run", "task", 0, 0, max_attempts=1,
        )
    assert not any(event["status"] == "模型呼叫異常，將自動重試" for event in events)


def test_intermediate_failed_model_call_logs_retry():
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    runner_status.configure(bus)
    attempts = iter([False, True])
    def action():
        if not next(attempts):
            raise RunnerError("boom")
        return "ok"
    assert retry_model_call(action, "run", "task", 0, 0, max_attempts=2) == "ok"
    assert sum(event.get("action") == "stop_set" and event["status"] == "模型呼叫異常，將自動重試" for event in events) == 1
