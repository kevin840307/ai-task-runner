"""Backend interface shared by all AI CLI integrations."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Sequence

from runner.errors import RunnerError
from runner.process_control import ProcessResult, run_process


class BackendError(RunnerError):
    """Raised when a backend CLI call cannot produce a usable result."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str = "",
        return_code: int | None = None,
        elapsed: float = 0.0,
        output: str = "",
        command_mode: str = "",
        session_source_event: str = "",
    ) -> None:
        super().__init__(message)
        self.session_id = session_id
        self.return_code = return_code
        self.elapsed = elapsed
        self.output = output
        self.command_mode = command_mode
        self.session_source_event = session_source_event


@dataclass(frozen=True)
class BackendResult:
    text: str
    session_id: str = ""


RUNNER_RULE_MARKER = "# AI Task Runner Rules"


def ensure_project_rules(root: Path, filename: str) -> Path:
    """Create or extend a backend project rule file."""
    path = root / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if RUNNER_RULE_MARKER not in existing:
        block = f"""

{RUNNER_RULE_MARKER}
- You may read files outside this project when needed.
- You may write, create, rename, or delete files only under: {root}
- Never modify validator files, runner state, or this rule file.
- Never run git add, git commit, or git push; leave Git acceptance and publication to human review.
- Python owns task order and completion state.
- Execute only the current task supplied by the runner.
- Complete the task with the smallest clean change possible; avoid unnecessary code, files, abstractions, dependencies, refactoring, or unrelated modifications.
- Never ask the user questions. Inspect the project, make the safest reasonable assumption, and continue.
"""
        path.write_text(existing.rstrip() + block, encoding="utf-8")
    return path


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


class AgentBackend(ABC):
    """Minimal contract required by the task runner."""

    name: ClassVar[str]
    default_command: ClassVar[str]

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
        input_text = self.prompt_stdin(prompt)
        command_prompt = "" if input_text is not None else prompt
        command_mode = "resume" if session_id else "new"
        command = self.build_command(command_prompt, session_id)
        started = time.monotonic()
        result = self._run(
            command,
            input_text,
            idle_timeout_after_change,
            change_detected,
        )
        elapsed = time.monotonic() - started
        output, return_code = result.output, result.return_code
        if return_code:
            failure_output = self.error_output(output)
            if result.idle_timed_out:
                raise BackendError(
                    f"{self.name} idle timed out without activity "
                    f"for {idle_timeout_after_change:g} seconds:\n"
                    f"{failure_output[-4000:]}"
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
            )
        decoded = self.decode(output)
        if not decoded.text.strip():
            raise BackendError(f"{self.name} returned an empty response")
        return decoded

    def _run(
        self,
        command: Sequence[str],
        input_text: str | None = None,
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
    ) -> ProcessResult:
        try:
            result = run_process(
                command,
                self.root,
                self.timeout,
                input_text,
                idle_timeout_after_change,
                change_detected,
            )
        except OSError as error:
            raise BackendError(f"{self.name} failed: {error}") from error
        if result.timed_out:
            if result.idle_timed_out:
                return result
            failure_output = self.error_output(result.output)
            raise BackendError(
                f"{self.name} timed out after {self.timeout} seconds:\n"
                f"{failure_output[-4000:]}"
            )
        return result

    def prepare_project(self) -> list[Path]:
        """Create optional backend-specific project files and return them."""
        return []

    def prompt_stdin(self, prompt: str) -> str | None:
        """Return prompt text to send through stdin instead of argv."""
        return None

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


# Backward-compatible alias used by releases before v1.0.
Backend = AgentBackend

__all__ = [
    "AgentBackend",
    "Backend",
    "BackendError",
    "BackendResult",
    "ensure_project_rules",
    "split_command",
]
