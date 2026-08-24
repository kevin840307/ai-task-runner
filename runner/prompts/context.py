"""Stable prompt data contract shared by bundled AI stages."""
from __future__ import annotations

from typing import Any

from ..config.defaults import MIN_PLANNED_TASKS
from .loader import ai_rules, always_instructions

PROMPT_CONTEXT_KEYS = frozenset({
    "always_instructions",
    "failure",
    "goal",
    "planning",
    "previous",
    "project",
    "rules",
    "session",
    "stage",
    "task",
    "tasks",
    "validation",
    "workflow",
})


def _task_data(task: Any | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "deliverable": task.deliverable,
        "acceptance_criteria": list(task.acceptance_criteria),
        "last_output": task.last_output,
        "last_review": task.last_review,
        "review_skipped": task.review_skipped,
        "review_skip_reason": task.review_skip_reason,
        "status": task.status,
    }


def _shared_constraints(state: Any) -> list[str]:
    tasks = [task for task in state.tasks if task.id.startswith(f"c{state.cycle:02d}-")]
    if not tasks:
        return []
    common = set(tasks[0].acceptance_criteria)
    for task in tasks[1:]:
        common.intersection_update(task.acceptance_criteria)
    return [item for item in tasks[0].acceptance_criteria if item in common][:8]


def build_stage_prompt_context(ctx: Any, stage: str, previous: Any | None = None) -> dict[str, Any]:
    """Build the only supported top-level variables for Jinja prompt templates."""
    state = ctx.state
    tasks = [_task_data(task) for task in state.tasks]
    validator_prompt = getattr(ctx.config, "validator_prompt", "") or ""
    ai_validator_prompt = getattr(ctx.config, "ai_validator_prompt", "") or ""
    return {
        "goal": state.goal,
        "stage": stage,
        "task": _task_data(ctx.task),
        "tasks": tasks,
        "workflow": {
            "cycle": state.cycle,
            "current": state.current,
            "validator_feedback": state.validator_output,
            "replan_feedback": state.replan_feedback,
            "completed_tasks": [task.title for task in state.tasks if task.status == "completed"][-20:],
            "review_skipped_tasks": [task for task in tasks if task and task["review_skipped"]][-20:],
            "shared_constraints": _shared_constraints(state),
        },
        "validation": {
            "validator_path": str(ctx.validator_path) if ctx.validator_path else "",
            "feedback": state.validator_output,
            "validator_prompt": validator_prompt,
            "ai_validator_prompt": ai_validator_prompt,
            "instructions": ai_validator_prompt or validator_prompt,
        },
        "project": {
            "root": str(ctx.root),
            "work": str(ctx.work),
        },
        "session": {
            "id": getattr(ctx.ai_client, "session_id", ""),
            "mode": ctx.execution.retry_mode,
        },
        "failure": {
            "attempt": ctx.execution.attempt,
            "message": ctx.execution.previous_error,
        },
        "planning": {
            "mode": "initial" if state.cycle == 1 else "repair",
            "minimum_tasks": MIN_PLANNED_TASKS,
            "source_instruction": "",
            "inspection_summary": "",
            "progress": {
                "cycle": state.cycle,
                "validator_feedback": state.validator_output[-8000:],
                "replan_feedback": state.replan_feedback[-4000:],
                "completed_tasks": [task.title for task in state.tasks if task.status == "completed"][-20:],
                "review_skipped_tasks": [
                    {"id": task.id, "title": task.title, "reason": task.review_skip_reason}
                    for task in state.tasks if task.review_skipped
                ][-20:],
            },
        },
        "previous": {
            "stage": getattr(previous, "stage", ""),
            "status": getattr(previous, "status", ""),
            "output": getattr(previous, "output", ""),
        } if previous is not None else None,
        "rules": ai_rules(ctx.root),
        "always_instructions": always_instructions(ctx.root),
    }


__all__ = ["PROMPT_CONTEXT_KEYS", "build_stage_prompt_context"]
