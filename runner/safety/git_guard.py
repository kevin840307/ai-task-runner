"""Compatibility facade for the optional safety extension."""
from __future__ import annotations

from ..extensions.safety import (
    BLOCKED_GIT_SUBCOMMANDS,
    _guard_main,
    _guarded_command as guarded_command,
    _guarded_environment as guarded_environment,
    git_subcommand,
)

__all__ = [
    "BLOCKED_GIT_SUBCOMMANDS",
    "git_subcommand",
    "guarded_environment",
    "guarded_command",
    "_guard_main",
]
