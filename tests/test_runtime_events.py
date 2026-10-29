from pathlib import Path
from types import SimpleNamespace

from runner.runtime import events


def test_event_bus_subscribe_deduplicates_unsubscribe_and_observer_failure_is_fail_open():
    bus = events.EventBus()
    received = []

    def broken(_event):
        raise RuntimeError("observer failed")

    bus.subscribe(broken)
    bus.subscribe(received.append)
    bus.subscribe(received.append)

    with events.scope(bus, {"source": "unit"}):
        events.publish("runner.test", "first", value=1)

    assert len(received) == 1
    assert received[0]["type"] == "runner.test"
    assert received[0]["action"] == "first"
    assert received[0]["source"] == "unit"
    assert received[0]["value"] == 1
    assert received[0]["schema_version"] == 1
    assert received[0]["runner_version"]

    bus.unsubscribe(received.append)
    with events.scope(bus):
        events.publish("runner.test", "second")
    assert len(received) == 1


def test_event_scope_binds_state_and_restores_outer_context_and_status():
    outer_bus = events.EventBus()
    inner_bus = events.EventBus()
    outer = []
    inner = []
    outer_bus.subscribe(outer.append)
    inner_bus.subscribe(inner.append)

    with events.scope(outer_bus, {"scope": "outer"}):
        events.set_status("Outer", "outer detail")
        with events.scope(inner_bus, {"scope": "inner"}):
            state = SimpleNamespace(
                run_id="run-1",
                cycle=2,
                current=1,
                completed=False,
                tasks=[
                    SimpleNamespace(
                        id="task-1",
                        title="One",
                        status="running",
                        attempts=3,
                    )
                ],
            )
            events.bind(state)
            events.publish("runner.test", "inside")

        events.publish("runner.test", "after")

    inside = next(item for item in inner if item["action"] == "inside")
    assert inside["scope"] == "inner"
    assert inside["run_id"] == "run-1"
    assert inside["cycle"] == 2
    assert inside["current"] == 1
    assert inside["completed"] is False
    assert inside["tasks"] == [
        {"id": "task-1", "title": "One", "status": "running", "attempts": 3}
    ]

    after = next(item for item in outer if item["action"] == "after")
    assert after["scope"] == "outer"
    assert after["status"] == "Outer"
    assert after["detail"] == "outer detail"
    assert "run_id" not in after


def test_status_start_stop_show_todo_and_runner_helpers_publish_expected_events():
    bus = events.EventBus()
    received = []
    bus.subscribe(received.append)
    state = SimpleNamespace(
        run_id="run-2",
        cycle=1,
        current=0,
        completed=False,
        tasks=[],
    )

    action = SimpleNamespace(
        name="execute",
        mode="write",
        actor="agent",
        label="Implementation",
        stage=SimpleNamespace(status="Executing", detail="stage detail"),
    )
    result = SimpleNamespace(
        status="pass",
        changed_files=["a.py"],
        error="",
    )

    with events.scope(bus):
        events.show_todo(state)
        events.set_status("Checking", "detail")
        events.start("Running", "work")
        events.stop()
        events.stop("Stopped", "manual")
        events.stage_started(action)
        events.stage_finished(action, result)
        events.service_wait_exhausted("execute", "HTTP 503")
        events.session_fresh("session-old")

    pairs = [(item["type"], item["action"]) for item in received]
    assert ("runner.progress", "bind") in pairs
    assert ("runner.status", "set") in pairs
    assert ("runner.status", "start") in pairs
    assert ("runner.status", "stop") in pairs
    assert ("runner.status", "stop_set") in pairs
    assert ("runner.stage", "start") in pairs
    assert ("runner.stage", "finish") in pairs
    assert ("runner.service", "wait_window_exhausted") in pairs
    assert ("runner.session", "fresh") in pairs

    stage_start = next(
        item for item in received
        if item["type"] == "runner.stage" and item["action"] == "start"
    )
    assert stage_start["stage"] == "execute"
    assert stage_start["mode"] == "write"
    assert stage_start["actor"] == "agent"
    assert stage_start["label"] == "Implementation"

    stage_finish = next(
        item for item in received
        if item["type"] == "runner.stage" and item["action"] == "finish"
    )
    assert stage_finish["result"] == "pass"
    assert stage_finish["changed_files"] == ["a.py"]

    fresh = next(item for item in received if item["type"] == "runner.session")
    assert fresh["previous_session"] == "session-old"


def test_touch_heartbeat_path_creates_parent_and_publish_refreshes_env_heartbeat(
    tmp_path: Path, monkeypatch
):
    direct = tmp_path / "nested" / "direct.heartbeat"
    events.touch_heartbeat_path(direct)
    assert direct.exists()

    heartbeat = tmp_path / "worker.heartbeat"
    monkeypatch.setenv(events.HEARTBEAT_ENV, str(heartbeat))
    bus = events.EventBus()
    with events.scope(bus):
        events.publish("runner.test", "heartbeat")
    assert heartbeat.exists()


def test_sleep_with_heartbeat_chunks_wait_and_touches_before_each_chunk_and_after(
    monkeypatch,
):
    touches = []
    sleeps = []
    monkeypatch.setattr(events, "touch_heartbeat", lambda: touches.append("touch"))
    monkeypatch.setattr(events.time, "sleep", lambda seconds: sleeps.append(seconds))

    events.sleep_with_heartbeat(2.5, interval=1.0)

    assert sleeps == [1.0, 1.0, 0.5]
    assert touches == ["touch", "touch", "touch", "touch"]


def test_retry_event_is_transport_neutral_and_keeps_payload():
    event = events.retry_event(
        "retrying",
        stage="execute",
        retry=2,
        wait_seconds=4,
    )

    assert event["schema_version"] == 1
    assert event["runner_version"]
    assert event["type"] == "runner.retry"
    assert event["action"] == "retry"
    assert event["message"] == "retrying"
    assert event["stage"] == "execute"
    assert event["retry"] == 2
    assert event["wait_seconds"] == 4
    assert isinstance(event["timestamp"], float)
