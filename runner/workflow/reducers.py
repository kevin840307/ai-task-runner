"""Small durable effects applied after a Stage result."""

from __future__ import annotations

from collections.abc import Sequence

from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..runtime import progress
from ..runtime.run_state import RunState, Task
from ..utils.text import bounded_text
from .stages.contracts import StageContext, StageResult
from .task_output import decode_tasks


def reduce_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.kind == "tasks":
        return _tasks(ctx, result)
    if result.kind == "task":
        return _task(ctx, result)
    if result.kind == "review":
        return _review(ctx, result)
    if result.kind == "validation":
        return _validation(ctx, result)
    return result


def _tasks(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status != "pass":
        return result
    source = result.data if result.data is not None else result.output
    tasks = decode_tasks(source, cycle=ctx.state.cycle)
    install_plan(ctx.state, tasks, ctx.ai_client.session_id)
    progress.show_todo(ctx.state)
    return result


def _task(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.task
    if task is None:
        ctx.save_session()
        return result
    task.attempts += 1
    task.changed_files = list(dict.fromkeys([*task.changed_files, *result.changed_files]))
    task.last_output = bounded_text(
        result.output if result.status == "pass" else str(result.error or result.output),
        MAX_TASK_OUTPUT_CHARS,
    )
    ctx.save_session()
    return result


def _review(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.task
    if task is not None and isinstance(result.data, dict):
        task.last_review = result.data
    if result.status == "pass":
        ctx.scratch.pop("review_client", None)
        progress.set_status("Review PASS", task.title if task else result.stage)
    elif result.status == "fail":
        progress.set_status("Review 未通過，依 routes 返回", result.output)
    return result


def _validation(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status in {"pass", "fail"}:
        ctx.state.validator_output = bounded_text(
            result.output, MAX_VALIDATOR_OUTPUT_CHARS
        )
        if result.status == "fail":
            ctx.set_stage("validator_failed", result.output)
            progress.set_status("驗證失敗，依 routes 處理", result.stage)
    return result


def install_plan(
    state: RunState,
    tasks: Sequence[Task],
    session_id: str,
) -> None:
    state.ai_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.completed = False


def finish_task(ctx: StageContext) -> None:
    state = ctx.state
    if state.current >= len(state.tasks):
        raise ConfigurationError("task-scoped workflow has no pending task")
    task = state.tasks[state.current]
    task.status = "completed"
    task.last_output = ""
    state.ai_session_id = ctx.ai_client.session_id
    state.current += 1
    progress.set_status("任務完成", task.title)


def finish_run(ctx: StageContext) -> None:
    if any(task.status != "completed" for task in ctx.state.tasks):
        raise ConfigurationError("workflow ended with pending planned tasks")
    ctx.state.ai_session_id = ""
    ctx.state.transition_previous = {}
    ctx.state.completed = True
    ctx.ai_client.session_id = ""
    ctx.set_stage("completed", "")
    progress.set_status("全部完成", "Workflow PASS")


__all__ = ["finish_run", "finish_task", "reduce_result"]
