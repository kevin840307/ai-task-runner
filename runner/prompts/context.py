"""Stable, minimal data contract for bundled Jinja prompts."""
from __future__ import annotations

from typing import Any

from .loader import ai_rules, always_instructions

PROMPT_CONTEXT_KEYS = frozenset({
    "always_instructions",
    "goal",
    "instructions",
    "planning",
    "previous",
    "project",
    "rules",
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
        "steps": list(task.steps),
    }


def build_stage_prompt_context(
    ctx: Any,
    stage: str,
    previous: Any | None = None,
) -> dict[str, Any]:
    """Return the only supported top-level variables for Stage templates."""
    state = ctx.state
    tasks = [_task_data(task) for task in state.tasks]
    validator_prompt = getattr(ctx.config, "validator_prompt", "") or ""
    ai_validator_prompt = getattr(ctx.config, "ai_validator_prompt", "") or ""
    return {
        "goal": state.goal,
        "instructions": "",
        "stage": stage,
        "task": _task_data(ctx.task),
        "tasks": tasks,
        "workflow": {
            "cycle": state.cycle,
            "validator_feedback": state.validator_output,
        },
        "validation": {
            "validator_path": str(ctx.validator_path) if ctx.validator_path else "",
            "feedback": state.validator_output,
            "instructions": ai_validator_prompt or validator_prompt,
        },
        "project": {"root": str(ctx.root)},
        "planning": {
            "mode": "initial" if state.cycle == 1 else "repair",
            "inspection_summary": "",
            "progress": {
                "cycle": state.cycle,
                "validator_feedback": state.validator_output[-8000:],
                "replan_feedback": state.replan_feedback[-4000:],
                "completed_tasks": [
                    task.title for task in state.tasks if task.status == "completed"
                ][-20:],
                "review_skipped_tasks": [
                    {"id": task.id, "title": task.title, "reason": task.review_skip_reason}
                    for task in state.tasks if task.review_skipped
                ][-20:],
            },
        },
        "previous": {
            "stage": getattr(previous, "stage", ""),
            "status": getattr(previous, "status", ""),
            "output": str(getattr(previous, "output", ""))[-8000:],
        },
        "rules": ai_rules(ctx.root),
        "always_instructions": always_instructions(ctx.root),
    }


__all__ = ["PROMPT_CONTEXT_KEYS", "build_stage_prompt_context"]
