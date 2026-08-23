"""Generic execution hooks used by optional intercepting extensions."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionContext:
    root: Path
    work: Path
    mode: str
    actor: str


@dataclass(frozen=True)
class HookViolation:
    message: str
    kind: str = "generic"
    paths: tuple[str, ...] = ()


class HookChain:
    def __init__(self) -> None:
        self._hooks: list[Any] = []

    def add(self, hook: Any) -> None:
        self._hooks.append(hook)

    def before(self, context: ExecutionContext) -> list[tuple[Any, Any]]:
        result: list[tuple[Any, Any]] = []
        for hook in self._hooks:
            before = getattr(hook, "before_execution", None)
            result.append((hook, before(context) if callable(before) else None))
        return result

    def change_detector(
        self,
        context: ExecutionContext,
        tokens: list[tuple[Any, Any]],
        base: Callable[[], bool] | None,
    ) -> Callable[[], bool]:
        detector = base or (lambda: False)
        for hook, token in reversed(tokens):
            wrap = getattr(hook, "wrap_change_detector", None)
            if callable(wrap):
                detector = wrap(context, token, detector)
        return detector

    def after(
        self,
        context: ExecutionContext,
        tokens: list[tuple[Any, Any]],
    ) -> list[HookViolation]:
        violations: list[HookViolation] = []
        for hook, token in reversed(tokens):
            after = getattr(hook, "after_execution", None)
            if callable(after):
                current = after(context, token)
                if current:
                    violations.extend(current)
        return violations

    def environment(self, environment: Mapping[str, str]) -> dict[str, str]:
        result = dict(environment)
        for hook in self._hooks:
            transform = getattr(hook, "process_environment", None)
            if callable(transform):
                result = transform(result)
        return result

    def command(self, command: Sequence[str], environment: Mapping[str, str]) -> list[str]:
        result = list(command)
        for hook in self._hooks:
            transform = getattr(hook, "process_command", None)
            if callable(transform):
                result = transform(result, environment)
        return result

    def instructions(self, root: Path) -> str:
        parts: list[str] = []
        for hook in self._hooks:
            provider = getattr(hook, "instructions", None)
            if callable(provider):
                text = provider(root).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)


__all__ = ["ExecutionContext", "HookChain", "HookViolation"]
