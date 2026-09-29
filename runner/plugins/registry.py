"""Single plugin discovery/configuration boundary for the Runner."""
from __future__ import annotations

import importlib
from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from ..errors import RunnerError

PLUGIN_ENTRYPOINT_GROUP = "ai_task_runner.plugins"
BUILTIN_PLUGINS = (
    "runner.plugins.console",
    "runner.plugins.context_compression",
    "runner.plugins.runtime",
    "runner.plugins.safety",
)


@lru_cache(maxsize=1)
def plugin_modules() -> tuple[Any, ...]:
    """Load explicit built-ins plus installed external plugins once."""
    modules = [importlib.import_module(name) for name in BUILTIN_PLUGINS]
    try:
        points = entry_points()
        selected = (
            points.select(group=PLUGIN_ENTRYPOINT_GROUP)
            if hasattr(points, "select")
            else points.get(PLUGIN_ENTRYPOINT_GROUP, ())
        )
        modules.extend(
            point.load() for point in sorted(selected, key=lambda item: item.name)
        )
    except Exception as error:
        raise RunnerError(f"plugin discovery failed: {error}") from error
    return tuple(modules)


@lru_cache(maxsize=1)
def discover_plugins() -> tuple[str, ...]:
    """Run process-level Stage/backend registration once."""
    loaded: list[str] = []
    for module in plugin_modules():
        setup = getattr(module, "setup", None)
        if callable(setup):
            setup()
        loaded.append(
            str(
                getattr(module, "PLUGIN_NAME", "")
                or getattr(module, "__name__", type(module).__name__)
            )
        )
    return tuple(loaded)


def register_plugins(runtime: Any) -> None:
    discover_plugins()
    for module in plugin_modules():
        register = getattr(module, "register", None)
        if callable(register):
            register(runtime)


def add_plugin_arguments(parser: Any) -> None:
    discover_plugins()
    for module in plugin_modules():
        configure = getattr(module, "add_arguments", None)
        if callable(configure):
            configure(parser)


def plugin_config_from_namespace(namespace: Any) -> dict[str, dict[str, Any]]:
    return _collect_plugin_config("config_from_namespace", namespace)


def plugin_config_from_request(request: Any) -> dict[str, dict[str, Any]]:
    return _collect_plugin_config("config_from_request", request)


def plugin_config_from_yaml(item: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _collect_plugin_config("config_from_yaml", item)


def _collect_plugin_config(method: str, source: Any) -> dict[str, dict[str, Any]]:
    discover_plugins()
    result: dict[str, dict[str, Any]] = {}
    for module in plugin_modules():
        name = str(getattr(module, "PLUGIN_NAME", "") or "")
        loader = getattr(module, method, None)
        if name and callable(loader):
            values = loader(source)
            if values:
                result[name] = values
    return result


def merge_plugin_config(
    base: Mapping[str, Mapping[str, Any]],
    overrides: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(base, Mapping) or not isinstance(overrides, Mapping):
        raise ValueError("plugins must be an object")
    if any(
        not isinstance(item, Mapping)
        for item in (*base.values(), *overrides.values())
    ):
        raise ValueError("each plugin configuration must be an object")
    result = {name: dict(values) for name, values in base.items()}
    for name, values in overrides.items():
        result[name] = {**result.get(name, {}), **dict(values)}
    return result


def normalize_plugin_config(
    config: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(config, Mapping):
        raise ValueError("plugins must be an object")
    discover_plugins()
    modules = {
        str(module.PLUGIN_NAME): module
        for module in plugin_modules()
        if getattr(module, "PLUGIN_NAME", "")
    }
    unknown = sorted(set(config) - set(modules))
    if unknown:
        raise ValueError("unknown plugins: " + ", ".join(unknown))
    result: dict[str, dict[str, Any]] = {}
    for name, module in modules.items():
        normalize = getattr(module, "normalize_config", None)
        values = dict(config.get(name, {}))
        result[name] = normalize(values) if callable(normalize) else values
    return result


def collect_plugin_instructions(root: Path) -> str:
    try:
        from ..bootstrap import current_runtime
        return current_runtime().hooks.instructions(root)
    except RuntimeError:
        return ""


__all__ = [
    "PLUGIN_ENTRYPOINT_GROUP",
    "add_plugin_arguments",
    "collect_plugin_instructions",
    "discover_plugins",
    "merge_plugin_config",
    "normalize_plugin_config",
    "plugin_config_from_namespace",
    "plugin_config_from_request",
    "plugin_config_from_yaml",
    "plugin_modules",
    "register_plugins",
]
