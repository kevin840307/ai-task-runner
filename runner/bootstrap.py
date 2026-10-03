"""Application/runtime bootstrap and plugin discovery."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config.runtime import RuntimeConfig
from .plugins.runtime import HookChain
from .plugins.registry import register_plugins
from .runtime import events
from .runtime.events import EventBus


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


@contextmanager
def runtime_scope(config: RuntimeConfig):
    global _current
    previous = _current
    runtime = Runtime(
        config=config,
        work=Path(config.project_root).resolve() / config.work_dir,
        events=EventBus(),
        hooks=HookChain(),
        resources=[],
    )
    _current = runtime
    context = {
        key: value
        for key, value in {
            "script_index": config.script_index,
            "script_total": config.script_total,
        }.items()
        if value is not None
    }
    try:
        with events.scope(runtime.events, context):
            register_plugins(runtime)
            yield runtime
    finally:
        _current = previous


def execute(config: RuntimeConfig) -> int:
    with runtime_scope(config):
        if config.script:
            from .script import execute_script
            return execute_script(config, execute)
        from .workflow_runner import WorkflowRunner
        return WorkflowRunner(config).run()


__all__ = ["Runtime", "current_runtime", "execute", "register_resources", "runtime_scope"]
