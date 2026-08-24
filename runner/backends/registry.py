"""Backend registration, configuration, and construction."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..ai.contracts import AIBackend, BackendMode
from ..ai.errors import BackendError
from ..config.defaults import DEFAULT_AGENT_TIMEOUT
from .base import BaseBackend
from .opencode import OpenCodeBackend
from .qwen import QwenBackend

BACKENDS: dict[str, type[BaseBackend]] = {
    QwenBackend.name: QwenBackend,
    OpenCodeBackend.name: OpenCodeBackend,
}


def backend_names() -> tuple[str, ...]:
    return tuple(BACKENDS)


def _backend_type(name: str) -> type[BaseBackend]:
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


def configure_sandbox_args(name: str, extra_args: Sequence[str], *, sandbox: bool) -> list[str]:
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
) -> AIBackend:
    backend_type = _backend_type(name)
    return backend_type(command or backend_type.default_command, root, extra_args, timeout)


__all__ = [
    "BACKENDS",
    "backend_names",
    "configure_backend_args",
    "configure_sandbox_args",
    "create_backend",
    "default_command",
    "sandbox_supported",
]
