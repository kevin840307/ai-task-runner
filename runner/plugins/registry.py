"""Plugin discovery and access to composed plugin-provided capabilities."""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

PLUGIN_ENTRYPOINT_GROUP = "ai_task_runner.plugins"


@lru_cache
def _plugin_modules() -> tuple[Any, ...]:
    package = importlib.import_module("runner.plugins")
    internal = [
        importlib.import_module(f"runner.plugins.{item.name}")
        for item in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name)
    ]
    points = entry_points()
    selected = (
        points.select(group=PLUGIN_ENTRYPOINT_GROUP)
        if hasattr(points, "select")
        else points.get(PLUGIN_ENTRYPOINT_GROUP, ())
    )
    external = [point.load() for point in sorted(selected, key=lambda item: item.name)]
    return tuple((*internal, *external))


def register_plugins(runtime: Any) -> None:
    for module in _plugin_modules():
        register = getattr(module, "register", None)
        if callable(register):
            register(runtime)


def add_plugin_arguments(parser: Any) -> None:
    for module in _plugin_modules():
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
    result: dict[str, dict[str, Any]] = {}
    for module in _plugin_modules():
        name = getattr(module, "PLUGIN_NAME", "")
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
        raise ValueError("plugins must be an object")  # noqa: TRY004
    values = (*base.values(), *overrides.values())
    if any(not isinstance(item, Mapping) for item in values):
        raise ValueError("each plugin configuration must be an object")
    result = {name: dict(values) for name, values in base.items()}
    for name, values in overrides.items():
        result[name] = {**result.get(name, {}), **dict(values)}
    return result


def normalize_plugin_config(
    config: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(config, Mapping):
        raise ValueError("plugins must be an object")  # noqa: TRY004
    modules = {
        module.PLUGIN_NAME: module
        for module in _plugin_modules()
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
    "merge_plugin_config",
    "normalize_plugin_config",
    "plugin_config_from_namespace",
    "plugin_config_from_request",
    "plugin_config_from_yaml",
    "register_plugins",
]
