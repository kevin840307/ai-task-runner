"""Backend registry.

To add a backend:
1. Create one module implementing AgentBackend.
2. Override configure_args only when the CLI needs stage-specific policy.
3. Import the class here and add one registry entry.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..config.defaults import DEFAULT_AGENT_TIMEOUT

from .base import AgentBackend, AgentMode, BackendError, BackendResult
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
    sandbox: bool = False,
) -> list[str]:
    backend_type = _backend_type(name)
    result = backend_type.configure_args(
        mode,
        extra_args,
        allow_project_read=allow_project_read,
    )
    return configure_sandbox_args(name, result, sandbox=sandbox)


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
    return bool(_backend_type(name).sandbox_flags)


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
    "BACKENDS",
    "AgentBackend",
    "AgentMode",
    "BackendError",
    "BackendResult",
    "backend_names",
    "configure_agent_args",
    "configure_sandbox_args",
    "create_backend",
    "default_command",
    "ensure_opencode_rules",
    "ensure_qwen_rules",
    "sandbox_supported",
]
