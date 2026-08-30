"""Optional logs, public events, and model diagnostics observer."""
from __future__ import annotations

import json
from pathlib import Path

from ..utils.files import atomic_write_text
from ..utils.logs import append_bounded_log


class ObservabilityObserver:
    def __init__(self, runtime) -> None:
        self.callback = runtime.config.event_callback
        self.json_events = runtime.config.json_events
        self.log_path = None if getattr(runtime.config, "script", None) else runtime.work / "log.txt"

    def __call__(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        if kind.startswith("model."):
            self._write_model_snapshot(event)
            self._write_log({
                key: value for key, value in event.items()
                if key not in {"text", "debug_dir"}
            })
            return
        if not kind.startswith(("runner.", "script.")):
            return
        public = {key: value for key, value in event.items() if key != "state"}
        if self.callback is not None:
            try:
                self.callback(public)
            except Exception:
                pass
        self._write_log({key: value for key, value in event.items() if key != "state"})
        if self.json_events:
            try:
                print(json.dumps(public), flush=True)
            except (BrokenPipeError, OSError):
                self.json_events = False

    def _write_model_snapshot(self, event: dict) -> None:
        debug_dir = str(event.get("debug_dir", ""))
        if not debug_dir:
            return
        root = Path(debug_dir)
        kind = str(event.get("type", ""))
        text = str(event.get("text", ""))
        path = root / ("current-prompt.txt" if kind == "model.prompt" else "last-result.txt")
        if kind == "model.result":
            prompt = root / "current-prompt.txt"
            try:
                if prompt.exists():
                    atomic_write_text(root / "last-prompt.txt", prompt.read_text(encoding="utf-8"))
            except OSError:
                pass
        atomic_write_text(path, text)

    def _write_log(self, event: dict) -> None:
        if self.log_path is None:
            return
        append_bounded_log(
            self.log_path,
            json.dumps(event, ensure_ascii=False) + "\n",
        )


def register(runtime) -> None:
    runtime.events.subscribe(ObservabilityObserver(runtime))
