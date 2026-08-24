"""Extension contracts used by the StageExecutor boundary."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


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
    """Fail-closed Stage policy chain; concrete policies live in extensions."""

    def __init__(self) -> None:
        self._hooks: list[Any] = []

    def add(self, hook: Any) -> None:
        if hook not in self._hooks:
            self._hooks.append(hook)

    def before(self, action: HookAction) -> list[tuple[Any, Any]]:
        tokens: list[tuple[Any, Any]] = []
        try:
            for hook in self._hooks:
                tokens.append((hook, hook.before_execution(action)))
        except BaseException:
            for hook, token in reversed(tokens):
                try:
                    hook.after_execution(action, token)
                except BaseException:
                    pass
            raise
        return tokens

    def after(self, action: HookAction, tokens: Sequence[tuple[Any, Any]]) -> list[Any]:
        violations: list[Any] = []
        first_error: BaseException | None = None
        for hook, token in reversed(list(tokens)):
            try:
                violations.extend(hook.after_execution(action, token))
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

    def process_command(self, command: Sequence[str], environment: dict[str, str]) -> list[str]:
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


def extension_instructions(root: Path) -> str:
    try:
        from ..bootstrap import current_runtime
        return current_runtime().hooks.instructions(root)
    except RuntimeError:
        return ""


__all__ = ["ExecutionHook", "HookAction", "HookChain", "HookViolation", "extension_instructions"]
