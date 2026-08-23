"""Small fail-open event bus for optional observers."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
        for handler in tuple(self._handlers):
            try:
                handler(event)
            except Exception:
                # Observability/UI must never stop the automation loop.
                continue


__all__ = ["EventBus", "EventHandler"]
