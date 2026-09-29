"""Plugin hook chain and always-on runtime observers."""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..utils import append_bounded_log, atomic_write_text, io_path


class HookAction(Protocol):
    root: Path
    work: Path
    mode: str
    actor: str


@dataclass(frozen=True)
class HookViolation:
    message: str
    kind: str = "policy"
    paths: tuple[str, ...] = ()


class ExecutionHook(Protocol):
    def before_execution(self, action: HookAction) -> Any: ...
    def after_execution(self, action: HookAction, token: Any) -> list[Any]: ...


class HookChain:
    """Fail-closed Stage policy chain; concrete policies live in plugins."""

    def __init__(self) -> None:
        self._hooks: list[Any] = []

    def add(self, hook: Any) -> None:
        if hook not in self._hooks:
            self._hooks.append(hook)

    def before(self, action: HookAction) -> list[tuple[Any, Any]]:
        tokens: list[tuple[Any, Any]] = []
        try:
            for hook in self._hooks:
                before = getattr(hook, "before_execution", None)
                if callable(before):
                    tokens.append((hook, before(action)))
        except BaseException:
            for hook, token in reversed(tokens):
                try:
                    after = getattr(hook, "after_execution", None)
                    if callable(after):
                        after(action, token)
                except BaseException:
                    pass
            raise
        return tokens

    def after(
        self,
        action: HookAction,
        tokens: Sequence[tuple[Any, Any]],
    ) -> list[Any]:
        violations: list[Any] = []
        first_error: BaseException | None = None
        for hook, token in reversed(list(tokens)):
            try:
                after = getattr(hook, "after_execution", None)
                if callable(after):
                    violations.extend(after(action, token))
            except BaseException as error:
                first_error = first_error or error
        if first_error is not None:
            raise first_error
        return violations

    def change_detector(
        self,
        action: HookAction,
        tokens: Sequence[tuple[Any, Any]],
        base: Callable[[], bool] | None,
    ) -> Callable[[], bool] | None:
        detector = base
        for hook, token in tokens:
            wrapper = getattr(hook, "wrap_change_detector", None)
            if callable(wrapper):
                detector = wrapper(action, token, detector or (lambda: False))
        return detector

    def process_environment(self, environment: dict[str, str]) -> dict[str, str]:
        current = dict(environment)
        for hook in self._hooks:
            transform = getattr(hook, "process_environment", None)
            if callable(transform):
                current = transform(current)
        return current

    def process_command(
        self,
        command: Sequence[str],
        environment: dict[str, str],
    ) -> list[str]:
        current = list(command)
        for hook in self._hooks:
            transform = getattr(hook, "process_command", None)
            if callable(transform):
                current = transform(current, environment)
        return current

    def instructions(self, root: Path) -> str:
        parts: list[str] = []
        for hook in self._hooks:
            provider = getattr(hook, "instructions", None)
            if callable(provider):
                text = str(provider(root) or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    def model_error(self, client: Any, error: Any) -> None:
        for hook in self._hooks:
            handler = getattr(hook, "model_error", None)
            if not callable(handler):
                continue
            try:
                handler(client, error)
            except Exception as plugin_error:
                error.diagnostics["plugin_error"] = (
                    f"{type(plugin_error).__name__}: {plugin_error}"
                )


_MAX_CALLS = 100
_MAX_BYTES = 50 * 1024 * 1024


def _history_pairs(history: Path) -> list[tuple[str, list[Path]]]:
    grouped: dict[str, list[Path]] = {}
    try:
        files = list(history.glob("*.txt"))
    except OSError:
        return []
    for path in files:
        for suffix in ("-prompt.txt", "-result.txt"):
            if path.name.endswith(suffix):
                grouped.setdefault(path.name[: -len(suffix)], []).append(path)
                break
    return sorted(grouped.items())


def _trim_history(history: Path) -> None:
    pairs = _history_pairs(history)
    size = 0
    for _, files in pairs:
        for path in files:
            try:
                size += path.stat().st_size
            except OSError:
                pass
    while pairs and (len(pairs) > _MAX_CALLS or size > _MAX_BYTES):
        _, files = pairs.pop(0)
        for path in files:
            try:
                size -= path.stat().st_size
                path.unlink(missing_ok=True)
            except OSError:
                pass


class HistoryObserver:
    def __call__(self, event: dict) -> None:
        kind = event.get("type")
        debug_dir = event.get("debug_dir")
        if (
            not debug_dir
            or kind not in {"model.prompt", "model.result", "model.parse_error"}
        ):
            return
        history = Path(debug_dir) / "history"
        text = str(event.get("text", ""))
        if kind == "model.parse_error":
            pairs = _history_pairs(history)
            if pairs:
                atomic_write_text(history / f"{pairs[-1][0]}-result.txt", text)
            return
        call_id = str(event.get("call_id", ""))
        if not call_id:
            return
        suffix = "prompt" if kind == "model.prompt" else "result"
        atomic_write_text(history / f"{call_id}-{suffix}.txt", text)
        _trim_history(history)


class ObservabilityObserver:
    def __init__(self, runtime) -> None:
        self.callback = runtime.config.event_callback
        self.json_events = runtime.config.json_events
        self.log_path = (
            None
            if getattr(runtime.config, "script", None)
            else runtime.work / "log.txt"
        )

    def __call__(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        if kind.startswith("model."):
            self._write_model_snapshot(event)
            self._write_log({
                key: value
                for key, value in event.items()
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
        self._write_log({
            key: value for key, value in event.items() if key != "state"
        })
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
        path = root / (
            "current-prompt.txt"
            if kind == "model.prompt"
            else "last-result.txt"
        )
        if kind == "model.result":
            prompt = root / "current-prompt.txt"
            try:
                if prompt.exists():
                    atomic_write_text(
                        root / "last-prompt.txt",
                        io_path(prompt).read_text(encoding="utf-8"),
                    )
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
    """Register the always-on runtime observers."""
    runtime.events.subscribe(HistoryObserver())
    runtime.events.subscribe(ObservabilityObserver(runtime))


__all__ = [
    "ExecutionHook",
    "HistoryObserver",
    "HookAction",
    "HookChain",
    "HookViolation",
    "ObservabilityObserver",
    "register",
]
