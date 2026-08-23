"""Human terminal UI observer; Runner does not import it."""
from __future__ import annotations

from ..app.ui import LiveUI, show_todo


class ConsoleObserver:
    def __init__(self, runtime) -> None:
        config = runtime.config
        self.ui = LiveUI(
            json_events=False,
            human_output=config.human_output,
            context={},
            log_path=None,
        )

    def __call__(self, event: dict) -> None:
        state = event.get("state")
        action = event.get("action")
        if state is not None and action == "bind":
            self.ui.bind(state)
            return
        if action == "set":
            self.ui.set(event.get("status", ""), event.get("detail", ""))
        elif action == "start":
            self.ui.start(event.get("status", ""), event.get("detail", ""))
        elif action == "stop":
            self.ui.stop()
        elif action == "stop_set":
            self.ui.stop(event.get("status", ""), event.get("detail", ""))
        elif state is not None:
            show_todo(state, self.ui)


def register(runtime) -> None:
    runtime.events.subscribe(ConsoleObserver(runtime))
