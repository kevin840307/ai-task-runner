"""Default workflow routing and durable-state reducers."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from typing import Any

from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..runtime import progress
from ..runtime.state import RunState, Task
from ..utils import bounded_text
from .default import FLOWS, STAGES
from .stages.base import StageContext, StageResult

Outcome = StageResult

def _field_status(result: Any, field: str) -> str:
    return "pass" if bool(result[field]) else "fail"



def _stage(name: str) -> dict[str, Any]:
    stage = deepcopy(STAGES[name])
    stage.setdefault("name", name)
    return stage


def _flow(name: str) -> list[dict[str, Any]]:
    return [_stage(stage) for stage in FLOWS[name]]


def _remaining_task_flow(ctx: StageContext) -> list[list[dict[str, Any]]]:
    remaining = max(0, len(ctx.state.tasks) - ctx.state.current)
    return [_flow("todo") for _ in range(remaining)]


def initial_flow(ctx: StageContext) -> list[object]:
    """Select resume-safe flow data without constructing Stage objects."""
    if ctx.state.completed:
        return []
    validators = _flow("validators")
    if ctx.state.stage == "validator_failed":
        return _flow("validator_repair")
    if ctx.state.tasks and ctx.state.current < len(ctx.state.tasks):
        return [_remaining_task_flow(ctx), *validators]
    if ctx.state.tasks:
        return validators
    return _flow("default")


def _restart_plan(ctx: StageContext, result: StageResult) -> StageResult:
    feedback = str(result.error or result.output)[-4000:]
    invalidate_plan(ctx, feedback)
    ctx.reset_sessions()
    progress.set_status("相同失敗持續，重新規劃", result.stage)
    return replace(
        result,
        stages=tuple(_flow("replan")),
        replace=True,
    )

def _finish_plan(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    if result.status != "pass" or not isinstance(result.data, list):
        return result
    install_plan(ctx.state, result.data, ctx.model.session_id)
    progress.show_todo(ctx.state)
    # Plan returns the execution flow. Pipeline executes this nested list first,
    # then naturally resumes the outer validators that follow PlanStage.
    return replace(result, stages=tuple(_remaining_task_flow(ctx)))

def _finish_execute(ctx: StageContext, result: StageResult) -> StageResult:
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


def _finish_review(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    task = ctx.require_task(result.stage)
    review = result.data if isinstance(result.data, dict) else None
    if review is not None:
        task.last_review = review

    if result.skipped:
        reason = str(result.error or result.output)[-1000:]
        task.last_review = {"completed": True, "reason": reason, "missing_items": [], "review_skipped": True}
        task.review_skipped = True
        task.review_skip_reason = reason
        complete_task(ctx.state, task, ctx.model.session_id)
        ctx.scratch.pop("review_model", None)
        progress.set_status("Review 異常，暫時跳過", f"{task.title} · final validator will decide")
        return result

    if result.status == "pass":
        complete_task(ctx.state, task, ctx.model.session_id)
        ctx.scratch.pop("review_model", None)
        progress.set_status("任務完成", task.title)
        return result

    if result.status == "fail":
        task.status = "pending"
        progress.set_status("任務未完成，進入 Repair", result.output)
        # This mini-flow runs immediately, then Pipeline returns to the remaining
        # Plan-generated [execute, review] groups.
        return replace(result, stages=tuple(_flow("repair")))
    return result

def _finish_validation(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status == "replan":
        return _restart_plan(ctx, result)
    ctx.state.validator_output = bounded_text(result.output, MAX_VALIDATOR_OUTPUT_CHARS)
    if result.status == "fail":
        _record_validator_failure(ctx, result)
        return replace(
            result,
            stages=tuple(_flow("validator_repair")),
            replace=True,
        )
    return result


def _finish_final_validation(ctx: StageContext, result: StageResult) -> StageResult:
    result = _finish_validation(ctx, result)
    if result.status == "pass":
        complete_run(ctx.state)
        ctx.model.session_id = ""
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
    invalidate_plan(ctx, "")
    progress.set_status("最終驗證失敗，保留修改並進入 Repair Plan", result.stage)


def needs_ai_validation(ctx: StageContext) -> bool:
    return bool(ctx.ai_validation or ctx.args.ai_validator_prompt.strip())



def install_plan(state: RunState, tasks: Sequence[Task], session_id: str) -> None:
    state.model_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.replan_feedback = ""


def complete_task(state: RunState, task: Task, session_id: str) -> None:
    task.status = "completed"
    task.last_output = ""
    state.model_session_id = session_id
    state.current += 1


def complete_run(state: RunState) -> None:
    state.validator_failure_key = ""
    state.validator_failure_count = 0
    state.model_session_id = ""
    state.replan_feedback = ""
    state.completed = True


def invalidate_plan(ctx: StageContext, feedback: str = "") -> None:
    state = ctx.state
    limit = ctx.args.full_replan_threshold
    if limit and state.cycle >= limit:
        raise ConfigurationError(f"max cycles reached: {limit}")
    state.cycle += 1
    state.current = len(state.tasks)
    state.completed = False
    state.replan_feedback = feedback[-4000:]



RESULT_HANDLERS = {
    "finish_plan": _finish_plan,
    "finish_execute": _finish_execute,
    "finish_repair": _finish_execute,
    "finish_review": _finish_review,
    "finish_validation": _finish_validation,
    "finish_final_validation": _finish_final_validation,
}


STATUS_RESOLVERS = {
    "completed_status": partial(_field_status, field="completed"),
    "validation_status": partial(_field_status, field="passed"),
}

CONDITIONS = {
    "needs_ai_validation": needs_ai_validation,
}

__all__ = ["CONDITIONS", "RESULT_HANDLERS", "STATUS_RESOLVERS", "initial_flow"]
