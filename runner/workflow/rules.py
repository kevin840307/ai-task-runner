"""Default workflow routing and durable-state reducers."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from functools import partial
from typing import Any

from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..runtime import progress
from ..runtime.run_state import RunState, Task
from ..utils import bounded_text
from .definitions import FLOWS, STAGES
from .stages.contracts import StageContext, StageResult


def _resolve_boolean_status(result: Any, field: str) -> str:
    return "pass" if bool(result[field]) else "fail"


def stage_definition(name: str) -> dict[str, Any]:
    stage = deepcopy(STAGES[name])
    stage.setdefault("name", name)
    return stage


def flow_definition(name: str) -> list[dict[str, Any]]:
    return [stage_definition(stage) for stage in FLOWS[name]]


def _remaining_task_flow(ctx: StageContext) -> list[list[dict[str, Any]]]:
    remaining = max(0, len(ctx.state.tasks) - ctx.state.current)
    return [flow_definition("todo") for _ in range(remaining)]


def initial_flow(ctx: StageContext) -> list[object]:
    """Select resume-safe flow data without constructing Stage objects."""
    if ctx.state.completed:
        return []
    validators = flow_definition("validators")
    if ctx.state.stage == "validator_failed":
        return flow_definition("validator_repair")
    if ctx.state.tasks and ctx.state.current < len(ctx.state.tasks):
        return [_remaining_task_flow(ctx), *validators]
    if ctx.state.tasks:
        return validators
    return flow_definition("default")


def _restart_plan(ctx: StageContext, result: StageResult) -> StageResult:
    feedback = str(result.error or result.output)[-4000:]
    invalidate_plan(ctx, feedback)
    ctx.reset_sessions()
    progress.set_status("相同失敗持續，重新規劃", result.stage)
    return replace(
        result,
        next_flow=tuple(flow_definition("replan")),
        replace_remaining=True,
    )


def handle_plan_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    if result.status != "pass" or not isinstance(result.data, list):
        return result
    install_plan(ctx.state, result.data, ctx.ai_client.session_id)
    progress.show_todo(ctx.state)
    return replace(result, next_flow=tuple(_remaining_task_flow(ctx)))


def handle_execute_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    task = ctx.require_task(result.stage)
    task.attempts += 1
    task.changed_files = list(dict.fromkeys([*task.changed_files, *result.changed_files]))
    if result.status == "pass":
        task.last_output = bounded_text(result.output, MAX_TASK_OUTPUT_CHARS)
    elif result.error is not None:
        task.last_output = bounded_text(str(result.error), MAX_TASK_OUTPUT_CHARS)
    ctx.save_session()
    return result


def handle_review_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
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
        complete_task(ctx.state, task, ctx.ai_client.session_id)
        ctx.scratch.pop("review_client", None)
        progress.set_status("Review 異常，暫時跳過", f"{task.title} · final validator will decide")
        return result

    if result.status == "pass":
        complete_task(ctx.state, task, ctx.ai_client.session_id)
        ctx.scratch.pop("review_client", None)
        progress.set_status("任務完成", task.title)
        return result

    if result.status == "fail":
        task.status = "pending"
        progress.set_status("任務未完成，進入 Repair", result.output)
        return replace(result, next_flow=tuple(flow_definition("repair")))
    return result


def handle_validation_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    ctx.state.validator_output = bounded_text(result.output, MAX_VALIDATOR_OUTPUT_CHARS)
    if result.status == "fail":
        _record_validator_failure(ctx, result)
        return replace(
            result,
            next_flow=tuple(flow_definition("validator_repair")),
            replace_remaining=True,
        )
    return result


def handle_final_validation_result(ctx: StageContext, result: StageResult) -> StageResult:
    result = handle_validation_result(ctx, result)
    if result.status == "pass":
        complete_run(ctx.state)
        ctx.ai_client.session_id = ""
        ctx.set_stage("completed", "")
        progress.set_status("全部完成", "Validator PASS")
        return replace(result, complete=True)
    return result


def _record_validator_failure(ctx: StageContext, result: StageResult) -> None:
    normalized = "\n".join(line.strip() for line in result.output.splitlines() if line.strip())
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if key == ctx.state.validator_failure_key:
        ctx.state.validator_failure_count += 1
    else:
        ctx.state.validator_failure_key = key
        ctx.state.validator_failure_count = 1
    ctx.set_stage("validator_failed", result.output)
    invalidate_plan(ctx)
    progress.set_status("最終驗證失敗，保留修改並進入 Repair Plan", result.stage)


def needs_ai_validation(ctx: StageContext) -> bool:
    return bool(ctx.validator_is_ai or ctx.config.ai_validator_prompt.strip())


def install_plan(state: RunState, tasks: Sequence[Task], session_id: str) -> None:
    state.ai_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.replan_feedback = ""


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    state.ai_session_id = session_id
    state.current += 1


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.ai_session_id = ""
    state.replan_feedback = ""
    state.completed = True


def invalidate_plan(ctx: StageContext, feedback: str = "") -> None:
    state = ctx.state
    limit = ctx.config.max_cycles
    if limit >= 0 and state.cycle >= limit:
        raise ConfigurationError(f"max cycles reached: {limit}")
    state.cycle += 1
    state.current = len(state.tasks)
    state.completed = False
    state.replan_feedback = feedback[-4000:]


RESULT_HANDLERS = {
    "handle_plan_result": handle_plan_result,
    "handle_execute_result": handle_execute_result,
    "handle_repair_result": handle_execute_result,
    "handle_review_result": handle_review_result,
    "handle_validation_result": handle_validation_result,
    "handle_final_validation_result": handle_final_validation_result,
}

STATUS_RESOLVERS = {
    "completed_status": partial(_resolve_boolean_status, field="completed"),
    "validation_status": partial(_resolve_boolean_status, field="passed"),
}

CONDITIONS = {"needs_ai_validation": needs_ai_validation}

__all__ = ["CONDITIONS", "RESULT_HANDLERS", "STATUS_RESOLVERS", "initial_flow"]
