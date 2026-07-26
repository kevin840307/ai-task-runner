"""Backend registry.

To add a backend:
1. Create one module implementing AgentBackend.
2. Import the class here.
3. Add one registry entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .base import AgentBackend, Backend, BackendError, BackendResult
from .opencode import OpenCodeBackend
from .qwen import QwenBackend, ensure_qwen_rules


BACKENDS: dict[str, type[AgentBackend]] = {
    QwenBackend.name: QwenBackend,
    OpenCodeBackend.name: OpenCodeBackend,
}


def backend_names() -> tuple[str, ...]:
    return tuple(BACKENDS)


def default_command(name: str) -> str:
    return BACKENDS[name].default_command


def create_backend(
    name: str,
    command: str | None,
    root: Path,
    extra_args: Sequence[str],
    timeout: int = 7200,
) -> AgentBackend:
    try:
        backend_type = BACKENDS[name]
    except KeyError as error:
        raise BackendError(f"unsupported backend: {name}") from error
    return backend_type(
        command or backend_type.default_command, root, extra_args, timeout
    )


__all__ = [
    "AgentBackend",
    "Backend",
    "BackendError",
    "BackendResult",
    "BACKENDS",
    "backend_names",
    "create_backend",
    "default_command",
    "ensure_qwen_rules",
]
