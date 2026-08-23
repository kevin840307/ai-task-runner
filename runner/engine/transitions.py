"""Small state mutations used by the core orchestration loop."""
from __future__ import annotations

import time
from collections.abc import Sequence

from .models import RunStage, RunState, Task
from .recovery import reset_task_recovery


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
    state.replan_feedback = ""


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    reset_task_recovery(task)
    state.agent_session_id = session_id
    state.current += 1


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.agent_session_id = ""
    state.replan_feedback = ""
    state.completed = True


def invalidate_plan(state: RunState, feedback: str = "") -> None:
    """Preserve project/task evidence but make the outer loop naturally plan again."""
    state.cycle += 1
    state.current = len(state.tasks)
    state.completed = False
    state.replan_feedback = feedback[-4000:]


def normalize_state(state: RunState) -> bool:
    """Repair small logical inconsistencies instead of turning them into a STOP path."""
    changed = False
    if state.completed and state.stage != "completed":
        state.completed = False
        changed = True

    first_pending = next(
        (index for index, task in enumerate(state.tasks) if task.status != "completed"),
        len(state.tasks),
    )
    if not state.completed:
        expected_current = first_pending if first_pending < len(state.tasks) else len(state.tasks)
        if state.current != expected_current:
            state.current = expected_current
            changed = True

    if state.stage == "completed" and not state.completed:
        state.stage = "validator_failed" if first_pending == len(state.tasks) else "created"
        changed = True
    return changed


__all__ = [
    "complete_run",
    "complete_task",
    "install_plan",
    "invalidate_plan",
    "normalize_state",
    "set_stage",
]
