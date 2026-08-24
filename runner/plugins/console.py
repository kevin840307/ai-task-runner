"""Console UI extension for terminal runner events."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import unicodedata

from ..runtime.run_state import RunState, Task


class LiveUI:
    """Human terminal rendering for semantic Runner events."""

    FRAMES = "|/-\\"

    def __init__(
        self,
        human_output: bool = True,
    ) -> None:
        self.human_output = human_output
        self.enabled = human_output and sys.stdout.isatty()
        self.fullscreen = self.enabled and supports_ansi_screen()
        self.state: RunState | None = None
        self.status = "準備中"
        self.detail = ""
        self._line_width = 0
        self._task_list_snapshot: tuple[tuple[str, str, str], ...] = ()
        self._last_plain_status_snapshot: tuple[object, ...] | None = None
        self._frame = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def bind(self, state: RunState) -> None:
        tasks_changed = tuple(
            (task.id, task.title, self._task_mark(state, index, task))
            for index, task in enumerate(state.tasks)
        ) != self._task_list_snapshot
        self.state = state
        if self.enabled and not self.fullscreen and tasks_changed:
            self.stop()
            self._draw_plain_task_list_if_changed(state)
            sys.stdout.flush()
        else:
            self.draw()

    def set(self, status: str, detail: str = "") -> None:
        with self._lock:
            self.status = status
            self.detail = detail
        self.draw()

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
        snapshot = (status, detail, state.cycle, completed_count, len(state.tasks))
        if self._thread is None and snapshot == self._last_plain_status_snapshot:
            return
        self._last_plain_status_snapshot = snapshot
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

    @staticmethod
    def _task_mark(state: RunState, index: int, task: Task) -> str:
        if task.status == "completed":
            return "x"
        if index == state.current and not state.completed:
            return ">"
        return " "

    def start(self, status: str, detail: str = "") -> None:
        if self._thread and (status, detail) == (self.status, self.detail):
            return
        self.stop()
        if not self.enabled:
            self.set(status, detail)
            snapshot = (status, detail)
            if snapshot == self._last_plain_status_snapshot:
                return
            self._last_plain_status_snapshot = snapshot
            if self.human_output:
                message = f"{status}: {detail}" if detail else status
                print(message, flush=True)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self.set(status, detail)
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


class ConsoleObserver:
    """Translate generic runtime status events into terminal UI updates."""

    def __init__(self, runtime) -> None:
        config = runtime.config
        self.ui = LiveUI(human_output=config.human_output)

    def __call__(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        if kind.startswith("script.item_"):
            self.ui.stop()
            if self.ui.human_output:
                index = event.get("script_index", "?")
                total = event.get("script_total", "?")
                if kind == "script.item_started":
                    detail = event.get("prompt_preview", "")
                elif kind == "script.item_completed":
                    detail = "PASS"
                else:
                    detail = f"FAILED ({event.get('exit_code', '?')})"
                print(
                    f"[Script {index}/{total}] {detail}",
                    file=sys.stderr if kind == "script.item_failed" else sys.stdout,
                    flush=True,
                )
            return
        if not kind.startswith("runner."):
            return
        state = event.get("state")
        action = event.get("action")
        if kind == "runner.progress" and state is not None:
            self.ui.bind(state)
        elif kind == "runner.status" and action == "set":
            self.ui.set(event.get("status", ""), event.get("detail", ""))
        elif kind == "runner.status" and action == "start":
            self.ui.start(event.get("status", ""), event.get("detail", ""))
        elif kind == "runner.status" and action == "stop_set":
            self.ui.stop(event.get("status", ""), event.get("detail", ""))
        elif kind == "runner.status" and action == "stop":
            self.ui.stop()


def register(runtime) -> None:
    runtime.events.subscribe(ConsoleObserver(runtime))
