"""Durable-state reducers used by declarative workflow stages."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..runtime import progress
from ..runtime.run_state import RunState, Task
from ..utils.text import bounded_text
from .stages.contracts import StageContext, StageResult
from .task_output import decode_tasks



def prepare_replan(ctx: StageContext, result: StageResult) -> StageResult:
    """Invalidate the current plan before Pipeline restarts the static flow."""
    feedback = str(result.error or result.output)[-4000:]
    invalidate_plan(ctx, feedback)
    ctx.reset_sessions()
    progress.set_status("相同失敗持續，重新規劃", result.stage)
    return result


def handle_tasks_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status != "pass":
        return result
    source = result.data if result.data is not None else result.output
    tasks = decode_tasks(source, cycle=ctx.state.cycle)
    install_plan(ctx.state, tasks, ctx.ai_client.session_id)
    progress.show_todo(ctx.state)
    return result


def handle_task_result(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.task
    if task is None:
        # A task-profile Stage may also be used as a normal top-level linear
        # Workflow step with a custom prompt. In that mode there is no durable
        # TODO to mutate; keep only the AI session continuity. Task-scoped SOPs
        # still always have a pending TODO and use the reducer below.
        ctx.save_session()
        return result

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
    task = ctx.task
    review = result.data if isinstance(result.data, dict) else None

    if task is None:
        # Linear review stages are valid without a TODO. Their PASS/FAIL result
        # is consumed by RecoveryPolicy; there is simply no per-task review
        # record to persist. Keep review-client lifecycle/status behavior.
        if result.skipped or result.status == "pass":
            ctx.scratch.pop("review_client", None)
        if result.skipped:
            progress.set_status(
                "Review 異常，暫時跳過", "final validator will decide"
            )
        elif result.status == "pass":
            progress.set_status("Review PASS", result.stage)
        elif result.status == "fail":
            progress.set_status("Review 未通過，進入 Recovery", result.output)
        return result

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


def reduce_result(ctx: StageContext, result: StageResult) -> StageResult:
    """Apply the one durable-state reducer selected by StageResult.kind."""
    if result.kind == "tasks":
        return handle_tasks_result(ctx, result)
    if result.kind == "task":
        return handle_task_result(ctx, result)
    if result.kind == "review":
        return handle_review_result(ctx, result)
    if result.kind == "validation":
        return handle_validation_result(ctx, result)
    return result


def finish_run(ctx: StageContext) -> None:
    """Mark the run complete after the top-level flow succeeds end-to-end."""
    if any(task.status != "completed" for task in ctx.state.tasks):
        raise ConfigurationError("workflow ended with pending planned tasks")
    complete_run(ctx.state)
    ctx.ai_client.session_id = ""
    ctx.set_stage("completed", "")
    progress.set_status("全部完成", "Workflow PASS")


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



def install_plan(
    state: RunState,
    tasks: Sequence[Task],
    session_id: str,
) -> None:
    state.ai_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.replan_feedback = ""
    state.task_step = 0


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    state.ai_session_id = session_id
    state.current += 1


def finish_task(ctx: StageContext) -> None:
    """Complete the current TODO after its task-scoped SOP succeeds."""
    state = ctx.state
    if state.current >= len(state.tasks):
        raise ConfigurationError("task-scoped workflow has no pending task to complete")
    task = state.tasks[state.current]
    complete_task(state, task, ctx.ai_client.session_id)
    progress.set_status("任務完成", task.title)


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.ai_session_id = ""
    state.replan_feedback = ""
    state.task_step = 0
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
    state.task_step = 0
    state.completed = False
    if reset_workflow:
        state.workflow_position = 0
    state.replan_feedback = feedback[-4000:]


__all__ = [
    "finish_run",
    "finish_task",
    "prepare_replan",
    "reduce_result",
]
