"""Application/runtime bootstrap and plugin discovery."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config.runtime import RuntimeConfig
from .plugins.contracts import HookChain
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


def _create_runtime(config: RuntimeConfig) -> Runtime:
    return Runtime(
        config=config,
        work=Path(config.project_root).resolve() / config.work_dir,
        events=EventBus(),
        hooks=HookChain(),
        resources=[],
    )


def _event_context(config: RuntimeConfig) -> dict[str, int]:
    return {
        key: value for key, value in {
            "script_index": config.script_index,
            "script_total": config.script_total,
        }.items() if value is not None
    }



@contextmanager
def runtime_scope(config: RuntimeConfig):
    """Activate one runtime and restore the caller runtime after completion."""
    global _current
    previous = _current
    runtime = _create_runtime(config)
    _current = runtime
    try:
        with events.scope(runtime.events, _event_context(config)):
            register_plugins(runtime)
            yield runtime
    finally:
        _current = previous


def execute(args: RuntimeConfig) -> int:
    with runtime_scope(args):
        if args.script:
            from .script_runner import execute_script
            return execute_script(args, execute)
        from .task_runner import TaskRunner
        return TaskRunner(args).run()


__all__ = ["Runtime", "current_runtime", "execute", "register_resources", "runtime_scope"]
