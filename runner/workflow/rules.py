"""Backward-compatible imports for workflow reducers."""

from .reducers import (
    complete_run,
    complete_task,
    finish_run,
    finish_task,
    handle_review_result,
    handle_task_result,
    handle_tasks_result,
    handle_validation_result,
    install_plan,
    invalidate_plan,
    prepare_replan,
    reduce_result,
)

__all__ = [
    "complete_run",
    "complete_task",
    "finish_run",
    "finish_task",
    "handle_review_result",
    "handle_task_result",
    "handle_tasks_result",
    "handle_validation_result",
    "install_plan",
    "invalidate_plan",
    "prepare_replan",
    "reduce_result",
]
