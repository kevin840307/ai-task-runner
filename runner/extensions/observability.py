"""Best-effort callback, JSON-lines, and log observers."""
from __future__ import annotations

import json
from pathlib import Path


class ObservabilityObserver:
    def __init__(self, runtime) -> None:
        self.callback = runtime.config.event_callback
        self.json_events = runtime.config.json_events
        self.log_path = runtime.work / "log.txt"

    def __call__(self, event: dict) -> None:
        public = {key: value for key, value in event.items() if key not in {"action", "state"}}
        if self.callback is not None:
            try:
                self.callback(public)
            except Exception:
                pass
        self._write_log(public)
        if self.json_events:
            try:
                print(json.dumps(public), flush=True)
            except (BrokenPipeError, OSError):
                self.json_events = False

    def _write_log(self, event: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass


def register(runtime) -> None:
    runtime.events.subscribe(ObservabilityObserver(runtime))
