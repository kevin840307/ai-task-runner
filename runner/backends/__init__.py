"""Backend registry.

To add a backend:
1. Create one module implementing AgentBackend.
2. Override configure_args only when the CLI needs stage-specific policy.
3. Import the class here and add one registry entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from runner.defaults import DEFAULT_AGENT_TIMEOUT
from .base import AgentBackend, AgentMode, Backend, BackendError, BackendResult
from .opencode import OpenCodeBackend, ensure_opencode_rules
from .qwen import QwenBackend, ensure_qwen_rules


BACKENDS: dict[str, type[AgentBackend]] = {
    QwenBackend.name: QwenBackend,
    OpenCodeBackend.name: OpenCodeBackend,
}


def backend_names() -> tuple[str, ...]:
    return tuple(BACKENDS)


def default_command(name: str) -> str:
    return BACKENDS[name].default_command


def _backend_type(name: str) -> type[AgentBackend]:
    try:
        return BACKENDS[name]
    except KeyError as error:
        raise BackendError(f"unsupported backend: {name}") from error


def configure_agent_args(
    name: str,
    mode: AgentMode,
    extra_args: Sequence[str],
    *,
    allow_project_read: bool = False,
) -> list[str]:
    backend_type = _backend_type(name)
    return backend_type.configure_args(
        mode,
        extra_args,
        allow_project_read=allow_project_read,
    )


def create_backend(
    name: str,
    command: str | None,
    root: Path,
    extra_args: Sequence[str],
    timeout: int = DEFAULT_AGENT_TIMEOUT,
) -> AgentBackend:
    backend_type = _backend_type(name)
    return backend_type(
        command or backend_type.default_command, root, extra_args, timeout
    )


__all__ = [
    "AgentBackend",
    "AgentMode",
    "Backend",
    "BackendError",
    "BackendResult",
    "BACKENDS",
    "backend_names",
    "configure_agent_args",
    "create_backend",
    "default_command",
    "ensure_opencode_rules",
    "ensure_qwen_rules",
]
