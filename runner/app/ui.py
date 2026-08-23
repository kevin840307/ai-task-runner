"""Terminal and JSON-event UI for runner progress."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..engine.models import RunState, Task
from ..version import __version__


class LiveUI:
    """Human terminal UI plus optional machine-readable progress events."""

    FRAMES = "|/-\\"

    def __init__(
        self,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        json_events: bool = False,
        human_output: bool = True,
        context: Mapping[str, Any] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.event_callback = event_callback
        self.json_events = json_events
        self.human_output = human_output
        self.context = dict(context or {})
        self.log_path = log_path
        self.enabled = human_output and not json_events and sys.stdout.isatty()
        self.fullscreen = self.enabled and supports_ansi_screen()
        self.state: RunState | None = None
        self.status = "準備中"
        self.detail = ""
        self._line_width = 0
        self._task_list_snapshot: tuple[tuple[str, str, str], ...] = ()
        self._last_progress_snapshot: tuple[Any, ...] | None = None
        self._frame = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def bind(self, state: RunState) -> None:
        self.state = state
        self.draw()
        snapshot: tuple[Any, ...] = (
            state.run_id,
            state.cycle,
            state.current,
            state.completed,
            tuple((task.id, task.title, task.status, task.attempts) for task in state.tasks),
        )
        if snapshot == self._last_progress_snapshot:
            return
        self._last_progress_snapshot = snapshot
        self._emit("runner.progress", include_detail=False)

    def set(self, status: str, detail: str = "") -> None:
        with self._lock:
            self.status = status
            self.detail = detail
        self.draw()
        self._emit("runner.status")

    def draw(self) -> None:
        if not self.enabled or not self.state:
            return
        with self._lock:
            state = self.state
            status = self._single_line_text(self.status)
            detail = self._single_line_text(self.detail)
            spinner = (
                self.FRAMES[self._frame % len(self.FRAMES)]
                if self._thread
                else " "
            )
        if self.fullscreen:
            lines = self._draw_fullscreen_lines(state, status, detail, spinner)
            sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")
        else:
            self._draw_plain_task_list_if_changed(state)
            self._draw_single_line(state, status, detail, spinner)
        sys.stdout.flush()

    def _draw_fullscreen_lines(
        self,
        state: RunState,
        status: str,
        detail: str,
        spinner: str,
    ) -> list[str]:
        width, height = shutil.get_terminal_size((120, 24))
        completed_count = sum(
            task.status == "completed" for task in state.tasks
        )
        header = [
            f"AI Task Runner  Cycle {state.cycle}  "
            f"Progress {completed_count}/{len(state.tasks)}",
            "",
        ]
        footer = ["", f"  {spinner} {status}"]
        if detail:
            footer.append(f"    {detail}")

        task_lines = [
            f"  [{self._task_mark(state, index, task)}] "
            f"{index + 1}. {task.title}"
            for index, task in enumerate(state.tasks)
        ]
        task_capacity = max(1, height - len(header) - len(footer))
        if len(task_lines) > task_capacity:
            task_capacity = max(1, task_capacity - 1)
            start = min(
                max(0, state.current - task_capacity // 2),
                max(0, len(task_lines) - task_capacity),
            )
            end = start + task_capacity
            task_lines = [
                f"  Tasks {start + 1}-{end}/{len(state.tasks)}"
            ] + task_lines[start:end]

        body = header + task_lines
        spacer = [""] * max(0, height - len(body) - len(footer))
        return [
            self._fit_terminal_line(line, width)
            for line in body + spacer + footer
        ]

    def _draw_single_line(
        self,
        state: RunState,
        status: str,
        detail: str,
        spinner: str,
    ) -> None:
        completed_count = sum(
            task.status == "completed" for task in state.tasks
        )
        message = (
            f"{spinner} {status}  "
            f"Cycle {state.cycle}  Progress {completed_count}/{len(state.tasks)}"
        )
        if detail:
            message += f"  {detail}"
        width = shutil.get_terminal_size((120, 20)).columns
        message = self._fit_terminal_line(message, width)
        message_width = self._display_width(message)
        padding = max(0, self._line_width - message_width)
        self._line_width = message_width
        sys.stdout.write("\r" + message + (" " * padding))

    def _draw_plain_task_list_if_changed(self, state: RunState) -> None:
        snapshot = tuple(
            (task.id, task.title, self._task_mark(state, index, task))
            for index, task in enumerate(state.tasks)
        )
        if snapshot == self._task_list_snapshot:
            return
        if self._line_width:
            sys.stdout.write("\n")
            self._line_width = 0
        self._task_list_snapshot = snapshot
        completed_count = sum(
            task.status == "completed" for task in state.tasks
        )
        width = shutil.get_terminal_size((120, 20)).columns
        lines = [
            f"AI Task Runner  Cycle {state.cycle}  "
            f"Progress {completed_count}/{len(state.tasks)}",
            "",
            *[
                f"  [{mark}] {index + 1}. {title}"
                for index, (_, title, mark) in enumerate(snapshot)
            ],
            "",
        ]
        sys.stdout.write(
            "\n".join(self._fit_terminal_line(line, width) for line in lines)
            + "\n"
        )

    @staticmethod
    def _single_line_text(text: str) -> str:
        return " ".join(text.splitlines())

    @staticmethod
    def _character_width(char: str) -> int:
        if unicodedata.combining(char):
            return 0
        return 2 if unicodedata.east_asian_width(char) in "WF" else 1

    @classmethod
    def _display_width(cls, text: str) -> int:
        return sum(cls._character_width(char) for char in text)

    @classmethod
    def _fit_terminal_line(cls, line: str, width: int) -> str:
        limit = max(1, width - 6)
        if cls._display_width(line) <= limit:
            return line
        suffix = "..."
        available = max(0, limit - len(suffix))
        used = 0
        end = 0
        for end, char in enumerate(line, start=1):
            char_width = cls._character_width(char)
            if used + char_width > available:
                end -= 1
                break
            used += char_width
        return line[:end] + suffix

    def _emit(self, event_type: str, *, include_detail: bool = True) -> None:
        event: dict[str, Any] = {
            "schema_version": 1,
            "runner_version": __version__,
            "type": event_type,
            "timestamp": time.time(),
            "status": self.status,
            "detail": self.detail if include_detail else "",
            **self.context,
        }
        if self.state is not None:
            event.update({
                "run_id": self.state.run_id,
                "cycle": self.state.cycle,
                "current": self.state.current,
                "completed": self.state.completed,
                "tasks": [
                    {
                        "id": task.id,
                        "title": task.title,
                        "status": task.status,
                        "attempts": task.attempts,
                    }
                    for task in self.state.tasks
                ],
            })
        if self.event_callback is not None:
            try:
                self.event_callback(event)
            except Exception:
                # Integration/UI failures must not stop the automation loop.
                pass
        self._write_log(event)
        if self.json_events:
            try:
                print(json.dumps(event), flush=True)
            except (BrokenPipeError, OSError):
                # A disconnected UI must not stop the automation loop.
                self.json_events = False

    def _write_log(self, event: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            # Log writes are best-effort debug output only.
            pass

    @staticmethod
    def _task_mark(state: RunState, index: int, task: Task) -> str:
        if task.status == "completed":
            return "x"
        if index == state.current and not state.completed:
            return ">"
        return " "

    def start(self, status: str, detail: str = "") -> None:
        self.stop()
        self.set(status, detail)
        if not self.enabled:
            if self.human_output and not self.json_events:
                message = f"{status}: {detail}" if detail else status
                print(message, flush=True)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        while not self._stop.wait(0.12):
            self._frame += 1
            self.draw()

    def stop(self, status: str | None = None, detail: str = "") -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=0.5)
            self._thread = None
        if status:
            self.set(status, detail)
        elif self.enabled and not self.fullscreen and self._line_width:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._line_width = 0


def supports_ansi_screen() -> bool:
    if os.name != "nt":
        return True
    return bool(
        os.environ.get("WT_SESSION")
        or os.environ.get("ANSICON")
        or os.environ.get("ConEmuANSI", "").upper() == "ON"
        or os.environ.get("TERM_PROGRAM")
    )


def show_todo(state: RunState, ui: LiveUI) -> None:
    ui.bind(state)
