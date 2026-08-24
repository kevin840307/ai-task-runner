"""Transient progress state plus fail-open observer events."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .state import RunState
from ..version import __version__

EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def publish(self, event: dict[str, Any]) -> None:
        common: dict[str, Any] = {
            "schema_version": 1,
            "runner_version": __version__,
            "timestamp": time.time(),
            **_context,
        }
        if _state is not None:
            common.update({
                "run_id": _state.run_id,
                "cycle": _state.cycle,
                "current": _state.current,
                "completed": _state.completed,
                "tasks": [
                    {"id": task.id, "title": task.title, "status": task.status, "attempts": task.attempts}
                    for task in _state.tasks
                ],
            })
        event = {**common, **event}
        for handler in tuple(self._handlers):
            try:
                handler(event)
            except Exception:
                continue


_bus: EventBus | None = None
_state: RunState | None = None
_context: dict[str, Any] = {}
_status = "準備中"
_detail = ""


def configure(bus: EventBus, context: dict[str, Any] | None = None) -> None:
    global _bus, _context
    _bus, _context = bus, dict(context or {})


def bind(state: RunState) -> None:
    global _state
    _state = state
    _publish("runner.progress", "bind")


def set_status(status: str, detail: str = "") -> None:
    global _status, _detail
    _status, _detail = status, detail
    _publish("runner.status", "set")


def start(status: str, detail: str = "") -> None:
    global _status, _detail
    _status, _detail = status, detail
    _publish("runner.status", "start")


def stop(status: str = "", detail: str = "") -> None:
    global _status, _detail
    if status:
        _status, _detail = status, detail
        _publish("runner.status", "stop_set")
    else:
        _publish("runner.status", "stop")


def show_todo(state: RunState | None = None) -> None:
    if state is not None:
        bind(state)
    else:
        _publish("runner.progress", "bind")



def publish(event_type: str, action: str, **payload: Any) -> None:
    """Publish a public runner event while preserving existing event fields."""
    if _bus is None:
        return
    event: dict[str, Any] = {
        "type": event_type,
        "action": action,
        "status": _status,
        "detail": _detail,
        "state": _state,
        **payload,
    }
    _bus.publish(event)


def stage_started(action: Any) -> None:
    global _status, _detail
    _status = str(getattr(action.stage, "status", "") or getattr(action, "name", ""))
    _detail = str(getattr(action.stage, "detail", "") or "")
    publish(
        "runner.stage",
        "start",
        stage=getattr(action, "name", ""),
        mode=getattr(action, "mode", "readonly"),
        actor=getattr(action, "actor", "stage"),
    )
    publish("runner.status", "start")


def stage_finished(action: Any, result: Any) -> None:
    publish(
        "runner.stage",
        "finish",
        stage=getattr(action, "name", ""),
        mode=getattr(action, "mode", "readonly"),
        actor=getattr(action, "actor", "stage"),
        result=getattr(result, "status", "error"),
        changed_files=list(getattr(result, "changed_files", []) or []),
        error=str(getattr(result, "error", "") or ""),
    )
    publish("runner.status", "stop")

def service_wait_exhausted(stage: str, error: str) -> None:
    publish("runner.service", "wait_window_exhausted", stage=stage, error=error)


def session_fresh(previous_session: str) -> None:
    publish("runner.session", "fresh", previous_session=previous_session)


def _publish(event_type: str, action: str) -> None:
    publish(event_type, action)


set = set_status

__all__ = ["EventBus", "EventHandler", "bind", "configure", "publish", "service_wait_exhausted", "session_fresh", "set", "set_status", "show_todo", "stage_finished", "stage_started", "start", "stop"]
