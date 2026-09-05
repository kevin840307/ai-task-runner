"""Stable, minimal data contract for bundled Jinja prompts."""
from __future__ import annotations

import json
from typing import Any

from ..utils.text import bounded_text
from .loader import ai_rules, always_instructions

PREVIOUS_OUTPUT_CHARS = 8_000
PREVIOUS_DATA_CHARS = 6_000
PREVIOUS_DATA_ITEMS = 12
PREVIOUS_DATA_TEXT_CHARS = 500


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
    }


def _prompt_value(value: Any, depth: int = 0) -> Any:
    """Project arbitrary Stage data into a small JSON-friendly prompt value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return bounded_text(value, PREVIOUS_DATA_TEXT_CHARS)
    if depth >= 3:
        return bounded_text(str(value), PREVIOUS_DATA_TEXT_CHARS)
    if isinstance(value, dict):
        return {
            str(key): _prompt_value(item, depth + 1)
            for key, item in list(value.items())[:PREVIOUS_DATA_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [
            _prompt_value(item, depth + 1)
            for item in value[:PREVIOUS_DATA_ITEMS]
        ]
    return bounded_text(str(value), PREVIOUS_DATA_TEXT_CHARS)


def _previous_data(value: Any) -> Any:
    """Keep structured previous-stage feedback useful without growing prompts unbounded."""
    projected = _prompt_value(value)
    if projected is None:
        return None
    encoded = json.dumps(projected, ensure_ascii=False, default=str)
    if len(encoded) <= PREVIOUS_DATA_CHARS:
        return projected

    if not isinstance(projected, dict):
        return {"truncated": True, "preview": bounded_text(encoded, PREVIOUS_DATA_CHARS)}

    result: dict[str, Any] = {}
    for key, item in projected.items():
        result[key] = item
        while len(json.dumps(result, ensure_ascii=False, default=str)) > PREVIOUS_DATA_CHARS:
            current = result.get(key)
            if isinstance(current, list) and current:
                result[key] = current[:-1]
                continue
            result.pop(key, None)
            result["truncated"] = True
            break
    return result


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
            "output": bounded_text(str(getattr(previous, "output", "")), PREVIOUS_OUTPUT_CHARS),
            "data": _previous_data(getattr(previous, "data", None)),
        },
        "rules": ai_rules(ctx.root),
        "always_instructions": always_instructions(ctx.root),
    }


__all__ = ["PROMPT_CONTEXT_KEYS", "build_stage_prompt_context"]
