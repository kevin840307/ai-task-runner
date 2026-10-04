"""Agent backend contract, subprocess base, and registry."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from ..config.defaults import DEFAULT_AGENT_TIMEOUT
from ..errors import RunnerError
from ..runtime.process_runner import ProcessResult, run_process

BackendMode = Literal["planning", "review", "validation", "no_tool", "runtime"]


@dataclass(frozen=True)
class BackendResult:
    text: str
    session_id: str = ""


class BackendError(RunnerError):
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
        diagnostics: dict[str, Any] | None = None,
        recovery_key: str = "",
    ) -> None:
        super().__init__(message)
        self.session_id = session_id
        self.return_code = return_code
        self.elapsed = elapsed
        self.output = output
        self.command_mode = command_mode
        self.session_source_event = session_source_event
        self.diagnostics = dict(diagnostics or {})
        self.recovery_key = recovery_key


class AgentBackend(Protocol):
    name: ClassVar[str]
    default_command: ClassVar[str]
    sandbox_flags: ClassVar[tuple[str, ...]]
    supports_sandbox: ClassVar[bool]
    root: Path
    base_command: list[str]
    extra_args: list[str]
    timeout: int

    def ask(
        self,
        prompt: str,
        session_id: str = "",
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
    ) -> BackendResult: ...


def split_command(command: str, windows: bool | None = None) -> list[str]:
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
    name: ClassVar[str]
    default_command: ClassVar[str]
    sandbox_flags: ClassVar[tuple[str, ...]] = ()
    supports_sandbox: ClassVar[bool] = False

    def __init__(
        self,
        command: str,
        root: Path,
        extra_args: Sequence[str],
        timeout: int = 7200,
    ) -> None:
        self.root = root
        self.base_command = [command] if Path(command).is_file() else split_command(command)
        self.extra_args = list(extra_args)
        self.timeout = timeout
        self.mode: BackendMode = "runtime"
        self.allow_project_read = False
        self.sandbox = False
        self._validate_command(command)

    def ask(
        self,
        prompt: str,
        session_id: str = "",
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
    ) -> BackendResult:
        command_mode = "resume" if session_id else "new"
        started = time.monotonic()
        result = self._run(
            self.build_command(prompt, session_id),
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
                    recovery_key=f"{self.name}:idle-timeout:{idle_timeout_after_change:g}",
                )
            events = self.parse_json_events(output)
            raise BackendError(
                f"{self.name} exit {return_code}:\n{failure_output[-4000:]}",
                session_id=self.find_session_id(events),
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
                self.process_environment(),
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

    def configure_runtime(
        self,
        mode: BackendMode,
        *,
        allow_project_read: bool = False,
        sandbox: bool = False,
    ) -> None:
        self.mode = mode
        self.allow_project_read = allow_project_read
        self.sandbox = sandbox

    def process_environment(self) -> dict[str, str]:
        return {}

    def prepare_project(self) -> list[Path]:
        return []

    @classmethod
    def configure_args(
        cls,
        mode: BackendMode,
        extra_args: Sequence[str],
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        return list(extra_args)

    @classmethod
    def model_from_args(cls, extra_args: Sequence[str]) -> str:
        values = list(extra_args)
        for index, value in enumerate(values):
            text = str(value)
            if text == "--model" and index + 1 < len(values):
                return str(values[index + 1]).strip()
            if text.startswith("--model="):
                return text.split("=", 1)[1].strip()
        return ""

    @classmethod
    def configure_model_args(
        cls,
        extra_args: Sequence[str],
        model: str,
    ) -> list[str]:
        result: list[str] = []
        values = list(extra_args)
        index = 0
        while index < len(values):
            value = str(values[index])
            if value == "--model":
                index += 2
                continue
            if value.startswith("--model="):
                index += 1
                continue
            result.append(value)
            index += 1
        model_name = str(model or "").strip()
        if model_name:
            result.extend(["--model", model_name])
        return result

    def update_goal_reference(self, goal_file: str | None) -> None:
        pass

    def context_snapshot(self, session_id: str) -> str:
        return ""

    def context_usage_percent(self, snapshot: str) -> float | None:
        return None

    def compress_session(self, session_id: str) -> str:
        return ""

    def stdin_prompt(self, prompt: str) -> str:
        return prompt

    @abstractmethod
    def build_command(self, prompt: str, session_id: str) -> list[str]: ...

    @abstractmethod
    def decode(self, raw: str) -> BackendResult: ...

    def error_output(self, raw: str) -> str:
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
    def extract_diagnostics(
        values: Sequence[Any],
        error_text: str = "",
    ) -> dict[str, Any]:
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
                if "num_turns" in value and isinstance(
                    value.get("num_turns"),
                    (int, float),
                ):
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
            Path(executable).is_file() or shutil.which(executable) is not None
        )
        if not available:
            raise BackendError(
                f"command not found: {executable or original_command}"
            )


BACKENDS: dict[str, type[BaseBackend]] = {}
_BUILTINS_READY = False


def _ensure_builtins() -> None:
    global _BUILTINS_READY
    if _BUILTINS_READY:
        return
    from .opencode import OpenCodeBackend
    from .qwen import QwenBackend

    BACKENDS.setdefault(QwenBackend.name, QwenBackend)
    BACKENDS.setdefault(OpenCodeBackend.name, OpenCodeBackend)
    _BUILTINS_READY = True


def register_backend(name: str, backend_class: type[BaseBackend]) -> None:
    _ensure_builtins()
    if not isinstance(name, str) or not name.strip():
        raise ValueError("backend name must be a non-empty string")
    if name in BACKENDS:
        raise ValueError(f"duplicate backend registration: {name}")
    if not isinstance(backend_class, type) or not issubclass(
        backend_class,
        BaseBackend,
    ):
        raise ValueError(f"backend {name} must extend BaseBackend")
    BACKENDS[name] = backend_class


def backend_names() -> tuple[str, ...]:
    _ensure_builtins()
    return tuple(BACKENDS)


def _backend_type(name: str) -> type[BaseBackend]:
    _ensure_builtins()
    try:
        return BACKENDS[name]
    except KeyError as error:
        raise BackendError(f"unsupported backend: {name}") from error


def default_command(name: str) -> str:
    return _backend_type(name).default_command


def configure_backend_args(
    name: str,
    mode: BackendMode,
    extra_args: Sequence[str],
    *,
    allow_project_read: bool = False,
    sandbox: bool = False,
) -> list[str]:
    result = _backend_type(name).configure_args(
        mode,
        extra_args,
        allow_project_read=allow_project_read,
    )
    return configure_sandbox_args(name, result, sandbox=sandbox)


def configure_model_args(
    name: str,
    extra_args: Sequence[str],
    model: str,
) -> list[str]:
    return _backend_type(name).configure_model_args(extra_args, model)


def model_from_args(
    name: str,
    extra_args: Sequence[str],
) -> str:
    return _backend_type(name).model_from_args(extra_args)


def configure_sandbox_args(
    name: str,
    extra_args: Sequence[str],
    *,
    sandbox: bool,
) -> list[str]:
    result = list(extra_args)
    flags = _backend_type(name).sandbox_flags
    if sandbox and flags and not any(flag in result for flag in flags):
        result.append(flags[0])
    return result


def sandbox_supported(name: str) -> bool:
    return _backend_type(name).supports_sandbox


def create_backend(
    name: str,
    command: str | None,
    root: Path,
    extra_args: Sequence[str],
    timeout: int = DEFAULT_AGENT_TIMEOUT,
) -> AgentBackend:
    backend_type = _backend_type(name)
    return backend_type(
        command or backend_type.default_command,
        root,
        extra_args,
        timeout,
    )


__all__ = [
    "AgentBackend",
    "BACKENDS",
    "BackendError",
    "BackendMode",
    "BackendResult",
    "BaseBackend",
    "backend_names",
    "configure_backend_args",
    "configure_model_args",
    "configure_sandbox_args",
    "create_backend",
    "default_command",
    "model_from_args",
    "register_backend",
    "sandbox_supported",
    "split_command",
]
