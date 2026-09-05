"""Canonical Task[] decoding shared by AI, Python, command, and future Stages."""
from __future__ import annotations

import json
from typing import Any

from ..ai.structured_output import require_object, require_text, require_text_list
from ..errors import RunnerError
from ..runtime.run_state import Task


def decode_tasks(value: Any, *, cycle: int, minimum: int = 1) -> list[Task]:
    """Decode either Task objects or the public {"tasks": [...]} contract."""
    if isinstance(value, list) and all(isinstance(item, Task) for item in value):
        tasks = list(value)
        if len(tasks) < minimum:
            raise RunnerError(f"tasks must contain at least {minimum} items")
        return tasks
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RunnerError(f"task producer must return valid JSON: {error}") from error
    raw = require_object(value).get("tasks")
    if not isinstance(raw, list) or len(raw) < minimum:
        raise RunnerError(f"tasks must contain at least {minimum} items")
    tasks: list[Task] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"tasks[{index}] must be an object")
        tasks.append(Task(
            id=f"c{cycle:02d}-t{index:03d}",
            title=require_text(item.get("title"), f"tasks[{index}].title"),
            description=require_text(item.get("description"), f"tasks[{index}].description"),
            deliverable=require_text(item.get("deliverable"), f"tasks[{index}].deliverable"),
            acceptance_criteria=require_text_list(
                item.get("acceptance_criteria", item.get("accept_criteria")),
                f"tasks[{index}].acceptance_criteria", allow_empty=False,
            ),
        ))
    return tasks


__all__ = ["decode_tasks"]
