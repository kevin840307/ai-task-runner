"""Generic stage-to-backend argument policy adapter."""
from __future__ import annotations

from typing import Sequence

from ..backends import configure_agent_args


def planning_agent_args(
    backend: str,
    extra_args: Sequence[str],
    allow_project_read: bool = False,
) -> list[str]:
    """Return backend arguments for a read-only planning session."""
    return configure_agent_args(
        backend,
        "planning",
        extra_args,
        allow_project_read=allow_project_read,
    )


def review_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    """Return backend arguments for a read-only review session."""
    return configure_agent_args(backend, "review", extra_args)


def no_tool_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    """Return backend arguments for a logically tool-free decision call."""
    return configure_agent_args(backend, "no_tool", extra_args)


def runtime_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    """Return backend arguments for an executor session."""
    return configure_agent_args(backend, "runtime", extra_args)


__all__ = [
    "no_tool_agent_args",
    "planning_agent_args",
    "review_agent_args",
    "runtime_agent_args",
]
