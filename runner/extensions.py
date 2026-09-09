"""Discover optional installed extensions before configuration is validated."""
from __future__ import annotations

from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any

from .errors import RunnerError

EXTENSION_GROUP = "ai_task_runner.extensions"


@lru_cache(maxsize=1)
def discover_extensions() -> tuple[str, ...]:
    """Load installed registration hooks once per process.

    An extension entry point may be a callable or an object exposing register().
    Registration is intentionally runtime-independent so Stage/backend types exist
    before Workflow validation.
    """
    loaded: list[str] = []
    try:
        points = entry_points()
        selected = points.select(group=EXTENSION_GROUP) if hasattr(points, "select") else points.get(EXTENSION_GROUP, ())
        for point in sorted(selected, key=lambda item: item.name):
            extension: Any = point.load()
            register = extension if callable(extension) else getattr(extension, "register", None)
            if not callable(register):
                raise RunnerError(
                    f"extension {point.name} must be callable or expose register()"
                )
            register()
            loaded.append(point.name)
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError(f"extension discovery failed: {error}") from error
    return tuple(loaded)


__all__ = ["EXTENSION_GROUP", "discover_extensions"]
