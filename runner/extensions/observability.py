"""Optional logs, public events, and model diagnostics observer."""
from __future__ import annotations

import json
import os
from pathlib import Path


class ObservabilityObserver:
    def __init__(self, runtime) -> None:
        self.callback = runtime.config.event_callback
        self.json_events = runtime.config.json_events
        self.log_path = runtime.work / "log.txt"

    def __call__(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        if kind.startswith("model."):
            self._write_model_snapshot(event)
            self._write_log({
                key: value for key, value in event.items()
                if key not in {"text", "debug_dir"}
            })
            return
        if not kind.startswith("runner."):
            return
        public = {key: value for key, value in event.items() if key not in {"action", "state"}}
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
                    self._atomic_write(root / "last-prompt.txt", prompt.read_text(encoding="utf-8"))
            except OSError:
                pass
        self._atomic_write(path, text)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_log(self, event: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass


def register(runtime) -> None:
    runtime.events.subscribe(ObservabilityObserver(runtime))
