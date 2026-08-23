"""Auto-discovered extension bootstrap; workflow code imports no extension."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from ..config import RuntimeConfig
from .events import EventBus
from .hooks import HookChain
from . import status


@dataclass
class Runtime:
    config: RuntimeConfig
    work: Path
    events: EventBus
    hooks: HookChain
    resources: list[Path]


_current: Runtime | None = None


def current() -> Runtime:
    if _current is None:
        raise RuntimeError("runner runtime is not bootstrapped")
    return _current


def register_resources(paths) -> None:
    try:
        runtime = current()
    except RuntimeError:
        return
    for value in paths:
        if value is None:
            continue
        path = Path(value).resolve()
        if path not in runtime.resources:
            runtime.resources.append(path)


def bootstrap(config: RuntimeConfig) -> Runtime:
    global _current
    runtime = Runtime(
        config=config,
        work=Path(config.project_root).resolve() / config.work_dir,
        events=EventBus(),
        hooks=HookChain(),
        resources=[],
    )
    _current = runtime
    status.configure(runtime.events, {
        key: value
        for key, value in {
            "script_index": config.script_index,
            "script_total": config.script_total,
        }.items()
        if value is not None
    })
    package = importlib.import_module("runner.extensions")
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        module = importlib.import_module(f"runner.extensions.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(runtime)
    return runtime


__all__ = ["Runtime", "bootstrap", "current", "register_resources"]
