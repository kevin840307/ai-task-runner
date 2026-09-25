"""Worker progress heartbeat shared by Supervisor and worker runtime."""
from __future__ import annotations

import os
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


__all__ = ["HEARTBEAT_ENV", "touch_heartbeat", "touch_heartbeat_path"]
