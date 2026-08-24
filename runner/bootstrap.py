"""Application/runtime bootstrap and extension discovery."""
from __future__ import annotations

import argparse
import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeConfig
from .extensions.base import HookChain
from .runtime.progress import EventBus
from .runtime import progress


@dataclass
class Runtime:
    config: RuntimeConfig
    work: Path
    events: EventBus
    hooks: HookChain
    resources: list[Path]


_current: Runtime | None = None


def current_runtime() -> Runtime:
    if _current is None:
        raise RuntimeError("runner runtime is not bootstrapped")
    return _current


def register_resources(paths) -> None:
    try:
        runtime = current_runtime()
    except RuntimeError:
        return
    for value in paths:
        if value is None:
            continue
        path = Path(value).resolve()
        if path not in runtime.resources:
            runtime.resources.append(path)


def bootstrap_runtime(config: RuntimeConfig) -> Runtime:
    global _current
    runtime = Runtime(
        config=config,
        work=Path(config.project_root).resolve() / config.work_dir,
        events=EventBus(),
        hooks=HookChain(),
        resources=[],
    )
    _current = runtime
    progress.configure(runtime.events, {
        key: value for key, value in {
            "script_index": config.script_index,
            "script_total": config.script_total,
        }.items() if value is not None
    })
    package = importlib.import_module("runner.extensions")
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        module = importlib.import_module(f"runner.extensions.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(runtime)
    return runtime


def execute(args: RuntimeConfig | argparse.Namespace) -> int:
    if not isinstance(args, RuntimeConfig):
        args = RuntimeConfig.from_namespace(args)
    bootstrap_runtime(args)
    if args.script:
        from .script_runner import execute_script
        return execute_script(args, execute)
    from .task_runner import TaskRunner
    return TaskRunner(args).run()


__all__ = ["Runtime", "bootstrap_runtime", "current_runtime", "execute", "register_resources"]
