"""Durable-state reducers used by declarative workflow stages."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from functools import partial
from typing import Any

from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..runtime import progress
from ..runtime.run_state import RunState, Task
from ..utils import bounded_text
from .stages.contracts import StageContext, StageResult


def _resolve_boolean_status(result: Any, field: str) -> str:
    return "pass" if bool(result[field]) else "fail"


def prepare_replan(ctx: StageContext, result: StageResult) -> StageResult:
    """Invalidate the current plan before Pipeline restarts the static flow."""
    feedback = str(result.error or result.output)[-4000:]
    invalidate_plan(ctx, feedback)
    ctx.reset_sessions()
    progress.set_status("相同失敗持續，重新規劃", result.stage)
    return result


def handle_plan_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status != "pass" or not isinstance(result.data, list):
        return result
    install_plan(ctx.state, result.data, ctx.ai_client.session_id)
    progress.show_todo(ctx.state)
    return result


def handle_task_result(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.require_task(result.stage)
    task.attempts += 1
    task.changed_files = list(
        dict.fromkeys([*task.changed_files, *result.changed_files])
    )
    if result.status == "pass":
        task.last_output = bounded_text(result.output, MAX_TASK_OUTPUT_CHARS)
    elif result.error is not None:
        task.last_output = bounded_text(str(result.error), MAX_TASK_OUTPUT_CHARS)
    ctx.save_session()
    return result


def handle_review_result(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.require_task(result.stage)
    review = result.data if isinstance(result.data, dict) else None
    if review is not None:
        task.last_review = review

    if result.skipped:
        reason = str(result.error or result.output)[-1000:]
        task.last_review = {
            "completed": True,
            "reason": reason,
            "missing_items": [],
            "review_skipped": True,
        }
        task.review_skipped = True
        task.review_skip_reason = reason
        ctx.scratch.pop("review_client", None)
        progress.set_status(
            "Review 異常，暫時跳過", f"{task.title} · final validator will decide"
        )
        return result

    if result.status == "pass":
        ctx.scratch.pop("review_client", None)
        progress.set_status("Review PASS", task.title)
    elif result.status == "fail":
        task.status = "pending"
        progress.set_status("任務未完成，進入 Repair", result.output)
    return result


def handle_validation_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status not in {"pass", "fail"}:
        return result
    ctx.state.validator_output = bounded_text(result.output, MAX_VALIDATOR_OUTPUT_CHARS)
    if result.status == "fail":
        _record_validator_failure(ctx, result)
    return result


def finish_run(ctx: StageContext) -> None:
    """Mark the run complete after the top-level flow succeeds end-to-end."""
    if any(task.status != "completed" for task in ctx.state.tasks):
        raise ConfigurationError("workflow ended with pending planned tasks")
    complete_run(ctx.state)
    ctx.ai_client.session_id = ""
    ctx.set_stage("completed", "")
    progress.set_status("全部完成", "Final Validator PASS")


def _record_validator_failure(ctx: StageContext, result: StageResult) -> None:
    normalized = "\n".join(
        line.strip() for line in result.output.splitlines() if line.strip()
    )
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if key == ctx.state.validator_failure_key:
        ctx.state.validator_failure_count += 1
    else:
        ctx.state.validator_failure_key = key
        ctx.state.validator_failure_count = 1
    ctx.set_stage("validator_failed", result.output)
    invalidate_plan(ctx, reset_workflow=False)
    progress.set_status("最終驗證失敗，保留修改並進入 Repair Plan", result.stage)


def needs_ai_validation(ctx: StageContext) -> bool:
    return bool(ctx.validator_is_ai or ctx.config.ai_validator_prompt.strip())


def install_plan(
    state: RunState,
    tasks: Sequence[Task],
    session_id: str,
) -> None:
    state.ai_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.replan_feedback = ""
    state.dynamic_steps = []
    state.dynamic_index = 0


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    state.ai_session_id = session_id
    state.current += 1


def finish_task(ctx: StageContext) -> None:
    """Complete the current TODO after its planned Stage sequence succeeds."""
    state = ctx.state
    if state.current >= len(state.tasks):
        raise ConfigurationError("generated workflow has no pending task to complete")
    task = state.tasks[state.current]
    complete_task(state, task, ctx.ai_client.session_id)
    progress.set_status("任務完成", task.title)


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.ai_session_id = ""
    state.replan_feedback = ""
    state.dynamic_steps = []
    state.dynamic_index = 0
    state.completed = True


def invalidate_plan(
    ctx: StageContext,
    feedback: str = "",
    *,
    reset_workflow: bool = True,
) -> None:
    state = ctx.state
    limit = ctx.config.max_cycles
    if limit >= 0 and state.cycle >= limit:
        raise ConfigurationError(f"max cycles reached: {limit}")
    state.cycle += 1
    state.current = len(state.tasks)
    state.dynamic_steps = []
    state.dynamic_index = 0
    state.completed = False
    if reset_workflow:
        state.workflow_position = 0
    state.replan_feedback = feedback[-4000:]


RESULT_HANDLERS = {
    "plan": handle_plan_result,
    "task": handle_task_result,
    "review": handle_review_result,
    "validation": handle_validation_result,
}

STATUS_RESOLVERS = {
    "completed": partial(_resolve_boolean_status, field="completed"),
    "validation": partial(_resolve_boolean_status, field="passed"),
}

CONDITIONS = {
    "ai_validation": needs_ai_validation,
}

__all__ = [
    "CONDITIONS",
    "RESULT_HANDLERS",
    "STATUS_RESOLVERS",
    "finish_run",
    "finish_task",
    "prepare_replan",
]
