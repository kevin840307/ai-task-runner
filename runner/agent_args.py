"""Generic stage-to-backend argument policy adapter."""
from __future__ import annotations

from typing import Sequence

from .backends import configure_agent_args

# Compatibility re-exports for callers from releases before backend policies
# moved under runner.backends.
from .backends.qwen_args import (
    QWEN_COMPUTER_USE_TOOLS,
    QWEN_DEFAULT_MAX_TOOL_CALLS,
    QWEN_NO_TOOL_COMPAT_TOOL,
    QWEN_PLANNING_EXCLUDED_TOOLS,
    QWEN_PLANNING_PROJECT_READ_TOOLS,
    QWEN_REVIEW_EXCLUDED_TOOLS,
    QWEN_RUNTIME_EXCLUDED_TOOLS,
    ensure_qwen_compat_tool,
    ensure_qwen_max_tool_calls,
    ensure_qwen_safe_mode,
    ensure_qwen_yolo,
    exclude_qwen_tools,
)


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
