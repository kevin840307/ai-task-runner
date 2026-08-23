"""Runner status facade; workflow code does not know UI/log observers."""
from __future__ import annotations

import time
from typing import Any

from ..engine.models import RunState
from ..version import __version__
from .events import EventBus

_bus: EventBus | None = None
_state: RunState | None = None
_context: dict[str, Any] = {}
_status = "準備中"
_detail = ""


def configure(bus: EventBus, context: dict[str, Any] | None = None) -> None:
    global _bus, _context
    _bus = bus
    _context = dict(context or {})


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
        _publish("runner.control", "stop")


def show_todo(state: RunState | None = None) -> None:
    if state is not None:
        bind(state)
    else:
        _publish("runner.progress", "bind")


def _publish(event_type: str, action: str) -> None:
    if _bus is None:
        return
    event: dict[str, Any] = {
        "schema_version": 1,
        "runner_version": __version__,
        "type": event_type,
        "timestamp": time.time(),
        "action": action,
        "status": _status,
        "detail": _detail,
        "state": _state,
        **_context,
    }
    if _state is not None:
        event.update({
            "run_id": _state.run_id,
            "cycle": _state.cycle,
            "current": _state.current,
            "completed": _state.completed,
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "attempts": task.attempts,
                }
                for task in _state.tasks
            ],
        })
    _bus.publish(event)


# compatibility naming used by prior Core/UI helpers
set = set_status

__all__ = ["bind", "configure", "set", "set_status", "show_todo", "start", "stop"]
