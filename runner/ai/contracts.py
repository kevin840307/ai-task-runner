"""AI client/backend contracts shared by workflow and backend implementations."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol

BackendMode = Literal["planning", "review", "no_tool", "runtime"]


@dataclass(frozen=True)
class BackendResult:
    text: str
    session_id: str = ""


class AIBackend(Protocol):
    name: ClassVar[str]
    default_command: ClassVar[str]
    sandbox_flags: ClassVar[tuple[str, ...]]
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

    def prepare_project(self) -> list[Path]: ...
    def update_goal_reference(self, goal_file: str | None) -> None: ...


class AIClientProtocol(Protocol):
    session_id: str
    root: Path
    extra_args: Sequence[str]

    def ask(
        self,
        prompt: str,
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
        timeout: int | None = None,
    ) -> str: ...

    def set_extra_args(self, extra_args: Sequence[str]) -> None: ...


__all__ = ["AIBackend", "AIClientProtocol", "BackendMode", "BackendResult"]
