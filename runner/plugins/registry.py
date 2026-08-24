"""Plugin discovery and access to composed plugin-provided capabilities."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any


def register_plugins(runtime: Any) -> None:
    package = importlib.import_module("runner.plugins")
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        module = importlib.import_module(f"runner.plugins.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(runtime)


def collect_plugin_instructions(root: Path) -> str:
    try:
        from ..bootstrap import current_runtime
        return current_runtime().hooks.instructions(root)
    except RuntimeError:
        return ""


__all__ = ["collect_plugin_instructions", "register_plugins"]
