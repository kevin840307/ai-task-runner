"""Worker progress heartbeat shared by Supervisor and worker runtime."""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..utils.files import io_path

HEARTBEAT_ENV = "AI_TASK_RUNNER_HEARTBEAT"


def touch_heartbeat() -> None:
    value = os.environ.get(HEARTBEAT_ENV, "").strip()
    if not value:
        return
    touch_heartbeat_path(Path(value))


def touch_heartbeat_path(path: Path) -> None:
    try:
        io_path(path.parent).mkdir(parents=True, exist_ok=True)
        io_path(path).touch(exist_ok=True)
    except OSError:
        pass


def sleep_with_heartbeat(seconds: float, *, interval: float = 60.0) -> None:
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        touch_heartbeat()
        step = min(interval, remaining)
        started = time.monotonic()
        time.sleep(step)
        remaining -= max(0.0, time.monotonic() - started)
    touch_heartbeat()


__all__ = [
    "HEARTBEAT_ENV",
    "sleep_with_heartbeat",
    "touch_heartbeat",
    "touch_heartbeat_path",
]
