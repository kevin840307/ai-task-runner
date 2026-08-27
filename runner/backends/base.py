"""Common subprocess implementation for CLI AI backends."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar

from ..ai.contracts import BackendMode, BackendResult
from ..ai.errors import BackendError
from ..runtime.process_runner import ProcessResult, run_process

def split_command(command: str, windows: bool | None = None) -> list[str]:
    """Split an executable command and remove Windows quote wrappers."""
    is_windows = os.name == "nt" if windows is None else windows
    parts = shlex.split(command, posix=not is_windows)
    if is_windows:
        parts = [
            part[1:-1]
            if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'"
            else part
            for part in parts
        ]
    return parts


class BaseBackend(ABC):
    """Minimal contract required by the task runner."""

    name: ClassVar[str]
    default_command: ClassVar[str]
    sandbox_flags: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        command: str,
        root: Path,
        extra_args: Sequence[str],
        timeout: int = 7200,
    ) -> None:
        self.root = root
        self.base_command = (
            [command]
            if Path(command).is_file()
            else split_command(command)
        )
        self.extra_args = list(extra_args)
        self.timeout = timeout
        self._validate_command(command)

    def ask(
        self,
        prompt: str,
        session_id: str = "",
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
    ) -> BackendResult:
        command_mode = "resume" if session_id else "new"
        command = self.build_command(prompt, session_id)
        started = time.monotonic()
        result = self._run(
            command,
            idle_timeout_after_change,
            change_detected,
            self.stdin_prompt(prompt),
        )
        elapsed = time.monotonic() - started
        output, return_code = result.output, result.return_code
        if return_code:
            failure_output = self.error_output(output)
            if result.idle_timed_out:
                raise BackendError(
                    f"{self.name} idle timed out without activity "
                    f"for {idle_timeout_after_change:g} seconds:\n"
                    f"{failure_output[-4000:]}",
                    recovery_key=(
                        f"{self.name}:idle-timeout:{idle_timeout_after_change:g}"
                    ),
                )
            events = self.parse_json_events(output)
            session_id = self.find_session_id(events)
            raise BackendError(
                f"{self.name} exit {return_code}:\n{failure_output[-4000:]}",
                session_id=session_id,
                return_code=return_code,
                elapsed=elapsed,
                output=output,
                command_mode=command_mode,
                session_source_event=self.find_session_source_event(events),
                diagnostics=self.extract_diagnostics(events, failure_output),
            )
        decoded = self.decode(output)
        if not decoded.text.strip():
            raise BackendError(f"{self.name} returned an empty response")
        return decoded

    def _run(
        self,
        command: Sequence[str],
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
        input_text: str | None = None,
    ) -> ProcessResult:
        try:
            result = run_process(
                command,
                self.root,
                self.timeout,
                idle_timeout_after_change,
                change_detected,
                input_text,
            )
        except OSError as error:
            raise BackendError(f"{self.name} failed: {error}") from error
        if result.timed_out:
            if result.idle_timed_out:
                return result
            failure_output = self.error_output(result.output)
            raise BackendError(
                f"{self.name} timed out after {self.timeout} seconds:\n"
                f"{failure_output[-4000:]}",
                recovery_key=f"{self.name}:timeout:{self.timeout}",
            )
        return result

    def prepare_project(self) -> list[Path]:
        """Create optional backend-specific project files and return them."""
        return []

    @classmethod
    def configure_args(
        cls,
        mode: BackendMode,
        extra_args: Sequence[str],
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        """Return backend-specific arguments for one runner stage."""
        return list(extra_args)

    def update_goal_reference(self, goal_file: str | None) -> None:
        """Optionally expose the original goal file through backend project metadata."""

    def context_snapshot(self, session_id: str) -> str:
        """Return optional read-only backend context diagnostics for logging."""
        return ""

    def context_usage_percent(self, snapshot: str) -> float | None:
        """Extract current context usage from a backend snapshot when supported."""
        return None

    def compress_session(self, session_id: str) -> str:
        """Optionally compact a backend session and return diagnostic text."""
        return ""

    def stdin_prompt(self, prompt: str) -> str:
        """Send model prompts through stdin to avoid command-line length limits."""
        return prompt

    @abstractmethod
    def build_command(self, prompt: str, session_id: str) -> list[str]:
        """Build one non-interactive CLI command."""

    @abstractmethod
    def decode(self, raw: str) -> BackendResult:
        """Decode CLI output and extract response text plus session ID."""

    def error_output(self, raw: str) -> str:
        """Summarize non-zero CLI output for retry prompts."""
        return raw

    def parse_json_events(self, raw: str) -> list[Any]:
        try:
            return [json.loads(raw)]
        except json.JSONDecodeError:
            pass

        events: list[Any] = []
        for line in raw.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events



    @staticmethod
    def extract_diagnostics(values: Sequence[Any], error_text: str = "") -> dict[str, Any]:
        """Extract backend-reported execution telemetry for logging only."""
        diagnostics: dict[str, Any] = {}
        text = error_text.lower()
        if "consecutive_identical_tool_calls" in text:
            diagnostics["loop_type"] = "consecutive_identical_tool_calls"
        elif "turn_tool_call_cap" in text:
            diagnostics["loop_type"] = "turn_tool_call_cap"
        elif "loop detection" in text:
            diagnostics["loop_type"] = "loop_detection"

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if "num_turns" in value and isinstance(value.get("num_turns"), (int, float)):
                    diagnostics["num_turns"] = int(value["num_turns"])
                usage = value.get("usage")
                if isinstance(usage, dict):
                    for source, target in (
                        ("input_tokens", "input_tokens"),
                        ("output_tokens", "output_tokens"),
                        ("cache_read_input_tokens", "cache_read_input_tokens"),
                        ("total_tokens", "total_tokens"),
                    ):
                        token_value = usage.get(source)
                        if isinstance(token_value, (int, float)):
                            diagnostics[target] = int(token_value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for value in values:
            visit(value)
        return diagnostics

    @staticmethod
    def find_session_source_event(values: Sequence[Any]) -> str:
        """Describe the first parsed event containing the discovered session id."""
        keys = ("session_id", "sessionID", "sessionId")

        def contains(value: Any) -> bool:
            if isinstance(value, dict):
                return any(value.get(key) for key in keys) or any(
                    contains(child) for child in value.values()
                )
            if isinstance(value, list):
                return any(contains(child) for child in value)
            return False

        for index, value in enumerate(values):
            if contains(value):
                event_type = value.get("type") if isinstance(value, dict) else None
                return f"event[{index}]" + (f":{event_type}" if event_type else "")
        return "-"

    @staticmethod
    def find_session_id(values: Sequence[Any]) -> str:
        session_id = ""

        def visit(value: Any) -> None:
            nonlocal session_id
            if session_id:
                return
            if isinstance(value, dict):
                candidate = (
                    value.get("session_id")
                    or value.get("sessionID")
                    or value.get("sessionId")
                )
                if candidate:
                    session_id = str(candidate)
                    return
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for value in values:
            visit(value)
        return session_id

    def _validate_command(self, original_command: str) -> None:
        executable = self.base_command[0] if self.base_command else ""
        available = executable and (
            Path(executable).is_file()
            or shutil.which(executable) is not None
        )
        if not available:
            raise BackendError(
                f"command not found: {executable or original_command}"
            )

__all__ = ["BaseBackend", "split_command"]
