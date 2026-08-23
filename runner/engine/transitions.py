"""Small state transitions used by the core orchestration loop."""
from __future__ import annotations

import time
from collections.abc import Sequence

from .models import RunStage, RunState, Task


def set_stage(
    state: RunState,
    stage: RunStage,
    detail: str = "",
    *,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else now
    if state.stage != stage:
        state.stage = stage
        state.stage_started_at = timestamp
    state.last_activity_at = timestamp
    state.last_error = detail[-1000:] if detail else ""


def install_plan(state: RunState, tasks: Sequence[Task], session_id: str) -> None:
    state.agent_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    task.progress_key = ""
    task.stagnant_attempts = 0
    state.agent_session_id = session_id
    state.current += 1


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.agent_session_id = ""
    state.completed = True


def prepare_repair_cycle(state: RunState) -> None:
    state.cycle += 1
    state.current = len(state.tasks)


__all__ = [
    "complete_run",
    "complete_task",
    "install_plan",
    "prepare_repair_cycle",
    "set_stage",
]
