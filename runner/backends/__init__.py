"""AI backend implementations and public registry helpers."""
from .opencode import OpenCodeBackend, ensure_opencode_rules
from .qwen import QwenBackend, ensure_qwen_rules
from .registry import (
    BACKENDS,
    backend_names,
    configure_backend_args,
    configure_sandbox_args,
    create_backend,
    default_command,
    register_backend,
    sandbox_supported,
)

__all__ = [
    "BACKENDS",
    "OpenCodeBackend",
    "QwenBackend",
    "backend_names",
    "configure_backend_args",
    "configure_sandbox_args",
    "create_backend",
    "default_command",
    "register_backend",
    "ensure_opencode_rules",
    "ensure_qwen_rules",
    "sandbox_supported",
]
